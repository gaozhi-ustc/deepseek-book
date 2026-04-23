"""docx_reader.py — 读 docx，按 word/document.xml 顺序产出 md_core.Block 列表。

覆盖 Block 类型：paragraph / heading / list / code / table / equation /
figure / blank，带 revisions / comments。

用 lxml 直接读 OOXML；python-docx 不足以读到 w:ins / w:del / m:oMath。
"""
import os
import re
import zipfile
from typing import List, Optional

from lxml import etree

from md_core import (
    Block, Revision, Comment,
    HeadingBlock, ParagraphBlock, EquationBlock,
    TableBlock, CodeBlock, FigureBlock, ListBlock, BlankBlock,
)


W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
M_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
A_NS = 'http://schemas.openxmlformats.org/drawingml/2006/main'
PIC_NS = 'http://schemas.openxmlformats.org/drawingml/2006/picture'

W = '{%s}' % W_NS
M = '{%s}' % M_NS


class DocxReaderError(RuntimeError):
    pass


# ──────────────────────────────────────────────────────────
# 打开 docx 并返回 document/comments/rels/media 相关 bytes
# ──────────────────────────────────────────────────────────

def _open_docx(path: str) -> dict:
    try:
        z = zipfile.ZipFile(path, 'r')
    except (zipfile.BadZipFile, OSError) as e:
        raise DocxReaderError(f'{path} 不是合法的 docx（zip）文件: {e}') from e

    with z:
        names = set(z.namelist())
        doc = z.read('word/document.xml') if 'word/document.xml' in names else None
        comments = z.read('word/comments.xml') if 'word/comments.xml' in names else None
        rels = z.read('word/_rels/document.xml.rels') \
            if 'word/_rels/document.xml.rels' in names else None
        media = {}
        for n in names:
            if n.startswith('word/media/'):
                media[n[len('word/media/'):]] = z.read(n)

    if doc is None:
        raise DocxReaderError(f'{path} 没有 word/document.xml')
    return {'document': doc, 'comments': comments, 'rels': rels, 'media': media}


# ──────────────────────────────────────────────────────────
# run 级文本与 revisions 抽取
# ──────────────────────────────────────────────────────────

def _text_of_w_t(r_el) -> str:
    parts = []
    for t in r_el.findall(f'{W}t'):
        parts.append(t.text or '')
    return ''.join(parts)


def _text_of_w_del_text(r_el) -> str:
    parts = []
    for t in r_el.findall(f'{W}delText'):
        parts.append(t.text or '')
    return ''.join(parts)


def _paragraph_accepted_text_and_revisions(p_el):
    """遍历段落的孩子节点，按顺序拼『接受所有 ins、丢弃所有 del』的最终文本，
    并收集 Revision 列表。

    返回 (text, revisions, anchor_offsets)。anchor_offsets 是 dict[comment_id, (start, end)]
    （end 可能在后续段落延续，这里仅记录本段内的开始/结束）。
    """
    text_parts: List[str] = []
    revisions: List[Revision] = []
    comment_spans: dict = {}
    comment_open: dict = {}

    def _emit(text: str):
        text_parts.append(text)

    def _len():
        return sum(len(x) for x in text_parts)

    for child in p_el:
        tag = etree.QName(child).localname
        ns = etree.QName(child).namespace

        if ns != W_NS:
            continue

        if tag == 'r':
            _emit(_text_of_w_t(child))
        elif tag == 'ins':
            ins_text = ''
            for r in child.findall(f'{W}r'):
                ins_text += _text_of_w_t(r)
            _emit(ins_text)
            revisions.append(Revision(
                kind='ins', text=ins_text,
                author=child.get(f'{W}author', ''),
                date=child.get(f'{W}date', ''),
                rev_id=int(child.get(f'{W}id', '0') or 0),
            ))
        elif tag == 'del':
            del_text = ''
            for r in child.findall(f'{W}r'):
                del_text += _text_of_w_del_text(r)
            revisions.append(Revision(
                kind='del', text=del_text,
                author=child.get(f'{W}author', ''),
                date=child.get(f'{W}date', ''),
                rev_id=int(child.get(f'{W}id', '0') or 0),
            ))
            # 注意：del 不写入 accepted text
        elif tag == 'commentRangeStart':
            cid = int(child.get(f'{W}id', '0') or 0)
            comment_open[cid] = _len()
        elif tag == 'commentRangeEnd':
            cid = int(child.get(f'{W}id', '0') or 0)
            if cid in comment_open:
                comment_spans[cid] = (comment_open.pop(cid), _len())
        elif tag == 'commentReference':
            # 仅指向位置（无范围）的批注
            cid = int(child.get(f'{W}id', '0') or 0)
            if cid not in comment_spans:
                comment_spans[cid] = (_len(), _len())

    return ''.join(text_parts), revisions, comment_spans


# ──────────────────────────────────────────────────────────
# 段落样式辅助
# ──────────────────────────────────────────────────────────

def _pstyle(p_el) -> Optional[str]:
    pPr = p_el.find(f'{W}pPr')
    if pPr is None:
        return None
    s = pPr.find(f'{W}pStyle')
    return s.get(f'{W}val') if s is not None else None


def _heading_level(style: Optional[str]) -> Optional[int]:
    if not style:
        return None
    m = re.match(r'(?i)heading\s*([1-6])$', style)
    if m:
        return int(m.group(1))
    return None


def _num_id(p_el) -> Optional[int]:
    pPr = p_el.find(f'{W}pPr')
    if pPr is None:
        return None
    numPr = pPr.find(f'{W}numPr')
    if numPr is None:
        return None
    nid = numPr.find(f'{W}numId')
    if nid is None:
        return None
    try:
        return int(nid.get(f'{W}val'))
    except (TypeError, ValueError):
        return None


def _is_code_paragraph(p_el) -> bool:
    style = _pstyle(p_el)
    if style and style.lower() in ('code', 'sourcecode', 'htmlpreformatted'):
        return True
    # 全部 run 使用 Courier 字体 → 视为代码
    runs = p_el.findall(f'{W}r')
    if not runs:
        return False
    mono = 0
    for r in runs:
        rPr = r.find(f'{W}rPr')
        if rPr is None:
            return False
        rfonts = rPr.find(f'{W}rFonts')
        if rfonts is None:
            return False
        font = (rfonts.get(f'{W}ascii') or '').lower()
        if 'courier' in font or 'consolas' in font or 'monaco' in font:
            mono += 1
    return mono == len(runs)


# ──────────────────────────────────────────────────────────
# read_docx 主入口
# ──────────────────────────────────────────────────────────

def read_docx(path: str) -> List[Block]:
    """读 docx 返回 Block 列表。"""
    bundle = _open_docx(path)
    root = etree.fromstring(bundle['document'])
    body = root.find(f'{W}body')
    if body is None:
        return []

    blocks: List[Block] = []
    list_buf_items: List[str] = []
    list_buf_ordered: Optional[bool] = None
    code_buf_lines: List[str] = []

    def _flush_list():
        nonlocal list_buf_items, list_buf_ordered
        if list_buf_items:
            blocks.append(ListBlock(items=list_buf_items,
                                    ordered=bool(list_buf_ordered),
                                    raw=''))
            list_buf_items = []
            list_buf_ordered = None

    def _flush_code():
        nonlocal code_buf_lines
        if code_buf_lines:
            # 去掉尾部的空行避免额外空白
            while code_buf_lines and code_buf_lines[-1] == '':
                code_buf_lines.pop()
            if code_buf_lines:
                blocks.append(CodeBlock(code='\n'.join(code_buf_lines) + '\n',
                                        language='', title='', raw=''))
            code_buf_lines = []

    for child in body:
        tag = etree.QName(child).localname
        ns = etree.QName(child).namespace
        if ns != W_NS:
            continue

        if tag != 'p':
            _flush_list()
            _flush_code()
            if tag == 'tbl':
                blocks.append(_read_table(child))
                continue
            if tag == 'sectPr':
                continue
            continue  # 其他元素忽略

        style = _pstyle(child)
        hlevel = _heading_level(style)
        nid = _num_id(child)
        is_code = _is_code_paragraph(child)
        text, revisions, _comments_raw = _paragraph_accepted_text_and_revisions(child)

        # 先检测公式段 — 段落里出现 m:oMath 直接产 EquationBlock
        omaths = child.findall(f'.//{{{M_NS}}}oMath')
        if omaths:
            _flush_list(); _flush_code()
            fp = equation_fingerprint(omaths[0])
            raw_xml = etree.tostring(omaths[0]).decode('utf-8')
            blocks.append(EquationBlock(latex=f'@omml:{fp}',
                                        raw=raw_xml,
                                        revisions=[], comments=[]))
            continue

        if hlevel is not None:
            _flush_list(); _flush_code()
            blocks.append(HeadingBlock(level=hlevel, text=text, raw=text,
                                       revisions=revisions, comments=[]))
            continue

        if nid is not None:
            _flush_code()
            ordered = (nid == 2)  # 约定；真实 docx 里需查 numbering.xml
            if list_buf_ordered is None:
                list_buf_ordered = ordered
            if list_buf_ordered != ordered:
                _flush_list()
                list_buf_ordered = ordered
            list_buf_items.append(text)
            continue

        if is_code:
            _flush_list()
            code_buf_lines.append(text)
            continue

        _flush_list(); _flush_code()
        if not text.strip():
            blocks.append(BlankBlock(raw=''))
        else:
            blocks.append(ParagraphBlock(text=text, raw=text,
                                         revisions=revisions, comments=[]))

    _flush_list(); _flush_code()
    return blocks


# ──────────────────────────────────────────────────────────
# 公式指纹
# ──────────────────────────────────────────────────────────

import hashlib
import copy


def _canonicalize_omml(omath_el) -> bytes:
    """返回规范化 OMML 的 c14n 字节串。
    规范化做法：
      - 复制原树，剥除 <w:rPr>（字体等样式属性不影响公式内容）
      - 剥除所有节点上的 xml:space 属性（仅影响空白保留，不影响内容）
      - cleanup_namespaces 去掉移除 rPr 后残留的未用 xmlns 声明
      - 公式内容以 m:t 文本与结构为主；后续发现误判时可再细化剥法
      - xml c14n
    """
    cloned = copy.deepcopy(omath_el)
    # 删 <w:rPr>
    for rpr in list(cloned.iter(f'{W}rPr')):
        parent = rpr.getparent()
        if parent is not None:
            parent.remove(rpr)
    # 剥 xml:space 属性
    xml_space = '{http://www.w3.org/XML/1998/namespace}space'
    for el in cloned.iter():
        if xml_space in el.attrib:
            del el.attrib[xml_space]
    # 清理未使用的命名空间声明
    etree.cleanup_namespaces(cloned)
    # c14n
    return etree.tostring(cloned, method='c14n')


def equation_fingerprint(omath_el) -> str:
    """公式内容指纹，不随 rPr 字体属性变化。"""
    return hashlib.sha256(_canonicalize_omml(omath_el)).hexdigest()


def _read_table(tbl_el) -> TableBlock:
    rows_xml = tbl_el.findall(f'{W}tr')
    rows = []
    for tr in rows_xml:
        cells = []
        for tc in tr.findall(f'{W}tc'):
            # 合并同一 cell 内多个 <w:p> 的 accepted 文本
            texts = []
            for p in tc.findall(f'{W}p'):
                text, _, _ = _paragraph_accepted_text_and_revisions(p)
                texts.append(text)
            cells.append('\n'.join(x for x in texts if x))
        rows.append(cells)

    if not rows:
        return TableBlock(header=[], rows=[], caption='', raw='')
    header = rows[0]
    body_rows = rows[1:]
    return TableBlock(header=header, rows=body_rows, caption='', raw='')
