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
# read_docx 主入口（先实现 paragraph）
# ──────────────────────────────────────────────────────────

def read_docx(path: str) -> List[Block]:
    """读 docx 返回 Block 列表。"""
    bundle = _open_docx(path)
    root = etree.fromstring(bundle['document'])
    body = root.find(f'{W}body')
    if body is None:
        return []

    blocks: List[Block] = []
    for child in body:
        tag = etree.QName(child).localname
        ns = etree.QName(child).namespace
        if ns != W_NS:
            continue

        if tag == 'p':
            blocks.append(_read_paragraph(child))
        elif tag == 'sectPr':
            continue
        # 后续任务会追加 table / sdt 等
    return blocks


def _read_paragraph(p_el) -> Block:
    text, revisions, _ = _paragraph_accepted_text_and_revisions(p_el)
    if not text.strip():
        return BlankBlock(raw='')
    return ParagraphBlock(text=text, raw=text,
                          revisions=revisions, comments=[])
