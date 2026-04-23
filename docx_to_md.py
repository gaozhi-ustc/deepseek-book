"""docx_to_md.py — 基线 Block vs 审校 Block 的分级比较、MdEdit 生成、应用。

核心入口：
  - match_blocks(base, rev) -> List[BlockMatch]
  - make_edits(base_md_text, reviewed_blocks) -> List[MdEdit]
  - make_edits_with_media(base_md_text, reviewed_blocks, media) -> List[MdEdit]
  - make_edits_with_comments(...) -> List[MdEdit]
  - apply_edits_to_md(baseline_text, edits) -> (new_text, warnings)
  - render_commit_message(edits, warnings, ...) -> str
"""
import difflib
import re
import os
import hashlib
import shutil as _shutil
import subprocess as _subprocess
from dataclasses import dataclass
from typing import List, Literal, Optional, Tuple

from md_core import (
    Block, BlankBlock,
    HeadingBlock, ParagraphBlock, EquationBlock,
    TableBlock, CodeBlock, FigureBlock, ListBlock,
    parse_md_blocks,
)
from md_diff_docx import _block_key


# ──────────────────────────────────────────────────────────
# 数据类
# ──────────────────────────────────────────────────────────

@dataclass
class BlockMatch:
    base_block: Optional[Block]
    reviewed_block: Optional[Block]
    kind: Literal['equal', 'text_edit', 'struct_change', 'insert', 'delete']


@dataclass
class MdEdit:
    target_line_range: Tuple[int, int]
    replacement: str
    reason: str
    provenance: str = ''


# ──────────────────────────────────────────────────────────
# 块相似度与结构判断
# ──────────────────────────────────────────────────────────

def _ratio(a: Block, b: Block) -> float:
    return difflib.SequenceMatcher(None, _block_key(a), _block_key(b),
                                   autojunk=False).ratio()


def _is_struct_change(a: Block, b: Block) -> bool:
    if isinstance(a, TableBlock) and isinstance(b, TableBlock):
        # 形状：列数或行数不同
        if len(a.header) != len(b.header):
            return True
        if len(a.rows) != len(b.rows):
            return True
        return False
    if isinstance(a, ListBlock) and isinstance(b, ListBlock):
        if a.ordered != b.ordered:
            return True
        if len(a.items) != len(b.items):
            return True
        return False
    return False


# ──────────────────────────────────────────────────────────
# match_blocks
# ──────────────────────────────────────────────────────────

def _deep_equal(a: Block, b: Block) -> bool:
    """对 _block_key 判定相等的块做更严格的深比较。"""
    if type(a) is not type(b):
        return False
    if isinstance(a, ListBlock):
        return a.ordered == b.ordered and a.items == b.items
    if isinstance(a, TableBlock):
        return a.header == b.header and a.rows == b.rows
    if isinstance(a, HeadingBlock):
        return a.level == b.level and a.text == b.text
    if isinstance(a, CodeBlock):
        return a.code == b.code  # language 不参与（读不出时从基线继承）
    if isinstance(a, FigureBlock):
        return a.alt == b.alt and a.path == b.path
    if isinstance(a, EquationBlock):
        return a.latex == b.latex
    if isinstance(a, ParagraphBlock):
        return a.text == b.text
    return False


def match_blocks(base: List[Block], rev: List[Block]) -> List[BlockMatch]:
    """两轮块匹配。
    第一轮：SequenceMatcher on _block_key → equal/delete/insert/replace opcodes
    第二轮：
      - 对 replace 段里每对块做 ratio；
         ratio >= 0.5 → text_edit 或 struct_change
         ratio <  0.5 → 拆成 delete + insert
      - 对 equal 对再做一次深比较（_block_key 可能忽略 ordered/cells 之类的字段），
         不等则升级为 text_edit 或 struct_change
    长度不相等的 replace 段按顺序 zip，多余的单独 delete / insert。
    """
    base_f = [b for b in base if not isinstance(b, BlankBlock)]
    rev_f  = [b for b in rev  if not isinstance(b, BlankBlock)]
    keys_a = [_block_key(b) for b in base_f]
    keys_b = [_block_key(b) for b in rev_f]

    sm = difflib.SequenceMatcher(None, keys_a, keys_b, autojunk=False)
    matches: List[BlockMatch] = []

    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            for a, b in zip(base_f[i1:i2], rev_f[j1:j2]):
                if _deep_equal(a, b):
                    matches.append(BlockMatch(a, b, 'equal'))
                elif _is_struct_change(a, b):
                    matches.append(BlockMatch(a, b, 'struct_change'))
                else:
                    matches.append(BlockMatch(a, b, 'text_edit'))
        elif op == 'delete':
            for a in base_f[i1:i2]:
                matches.append(BlockMatch(a, None, 'delete'))
        elif op == 'insert':
            for b in rev_f[j1:j2]:
                matches.append(BlockMatch(None, b, 'insert'))
        elif op == 'replace':
            a_chunk = base_f[i1:i2]
            b_chunk = rev_f[j1:j2]
            pairs = min(len(a_chunk), len(b_chunk))
            for k in range(pairs):
                a, b = a_chunk[k], b_chunk[k]
                # 同位置同类 Figure/Table/Equation 无条件视为 text_edit / struct_change
                # （路径/结构/公式差异大使 ratio 低，但业务语义上是同一个块被改）
                same_figure = (isinstance(a, FigureBlock) and isinstance(b, FigureBlock))
                same_table  = (isinstance(a, TableBlock)  and isinstance(b, TableBlock))
                same_equation = (isinstance(a, EquationBlock) and isinstance(b, EquationBlock))
                if same_figure or same_equation:
                    matches.append(BlockMatch(a, b, 'text_edit'))
                    continue
                if same_table:
                    if _is_struct_change(a, b):
                        matches.append(BlockMatch(a, b, 'struct_change'))
                    else:
                        matches.append(BlockMatch(a, b, 'text_edit'))
                    continue

                r = _ratio(a, b)
                if r >= 0.5:
                    if _is_struct_change(a, b):
                        matches.append(BlockMatch(a, b, 'struct_change'))
                    else:
                        matches.append(BlockMatch(a, b, 'text_edit'))
                else:
                    matches.append(BlockMatch(a, None, 'delete'))
                    matches.append(BlockMatch(None, b, 'insert'))
            for a in a_chunk[pairs:]:
                matches.append(BlockMatch(a, None, 'delete'))
            for b in b_chunk[pairs:]:
                matches.append(BlockMatch(None, b, 'insert'))

    return matches


# ──────────────────────────────────────────────────────────
# 行号定位 — 用 md_core.tokenize 的 block.raw 对齐原文
# ──────────────────────────────────────────────────────────

def parse_md_blocks_with_spans(md_text: str):
    """返回 [(Block, start_line, end_line)]，行号 0-indexed 半开区间。

    实现：
      - 拿到 Block 列表
      - 每个 Block.raw 在原文里按首行匹配定位起点
      - end = start + raw 行数
    对 BlankBlock 占一行；对无 raw 的 Block 宽松兜底 cursor~cursor+1。
    """
    blocks = parse_md_blocks(md_text)
    lines = md_text.splitlines(keepends=True)
    result = []
    cursor = 0
    for b in blocks:
        if isinstance(b, BlankBlock):
            start = cursor
            end = cursor + 1 if cursor < len(lines) else cursor
            cursor = end
            result.append((b, start, end))
            continue
        raw = b.raw if hasattr(b, 'raw') else ''
        if not raw:
            start = cursor
            end = cursor + 1 if cursor < len(lines) else cursor
            cursor = end
            result.append((b, start, end))
            continue

        raw_lines = raw.split('\n')
        n = len(raw_lines)
        # 期望从 cursor 起就是该 block；若不是，向前扫描至多 4 行
        matched_start = None
        limit = min(cursor + 4, len(lines))
        for k in range(cursor, limit):
            # 构造 lines[k:k+n] 的拼接（去尾换行）作为比较串
            slice_text = ''.join(lines[k:k + n])
            expected = '\n'.join(raw_lines)
            # 若 slice_text 比 expected 多一个换行，补齐
            if slice_text.rstrip('\n') == expected.rstrip('\n'):
                matched_start = k
                break
        if matched_start is None:
            matched_start = cursor
        start = matched_start
        end = start + n
        cursor = end
        result.append((b, start, end))
    return result


# ──────────────────────────────────────────────────────────
# _render_block_md — 把 Block 渲染回 md 源码
# ──────────────────────────────────────────────────────────

def _render_block_md(block: Block) -> str:
    """把一个 Block 渲染回单块 md 源码（不含末尾换行）。"""
    if isinstance(block, HeadingBlock):
        return '#' * block.level + ' ' + block.text
    if isinstance(block, ParagraphBlock):
        return block.text
    if isinstance(block, EquationBlock):
        latex = block.latex
        if latex.startswith('@omml:'):
            return f'<!-- REVIEW: formula content see attachments -->'
        return f'$${latex}$$'
    if isinstance(block, CodeBlock):
        return f'```{block.language}\n{block.code.rstrip()}\n```'
    if isinstance(block, ListBlock):
        if block.ordered:
            return '\n'.join(f'{i+1}. {it}' for i, it in enumerate(block.items))
        return '\n'.join(f'- {it}' for it in block.items)
    if isinstance(block, TableBlock):
        head = '| ' + ' | '.join(block.header) + ' |'
        sep  = '|' + '|'.join(['---'] * len(block.header)) + '|'
        rows = '\n'.join('| ' + ' | '.join(r) + ' |' for r in block.rows)
        return '\n'.join([head, sep, rows]) if rows else '\n'.join([head, sep])
    if isinstance(block, FigureBlock):
        return f'![{block.alt}]({block.path})'
    return ''


def _find_insertion_line(matches_with_span: list, idx: int) -> int:
    """给 matches_with_span 里第 idx 条 insert，找到前一个 equal/text_edit
    的 end_line 作为插入行；没有则返回 0。
    """
    for j in range(idx - 1, -1, -1):
        m, span = matches_with_span[j]
        if m.kind in ('equal', 'text_edit') and span is not None:
            return span[1]
    return 0


# ──────────────────────────────────────────────────────────
# make_edits — 产出 MdEdit 列表
# ──────────────────────────────────────────────────────────

def make_edits(baseline_md_text: str,
               reviewed_blocks: List[Block]) -> List[MdEdit]:
    baseline_with_spans = parse_md_blocks_with_spans(baseline_md_text)
    base_blocks = [b for (b, _, _) in baseline_with_spans
                   if not isinstance(b, BlankBlock)]
    base_spans = {id(b): (s, e) for (b, s, e) in baseline_with_spans
                  if not isinstance(b, BlankBlock)}

    rev_blocks = [b for b in reviewed_blocks if not isinstance(b, BlankBlock)]

    matches = match_blocks(base_blocks, rev_blocks)

    matches_with_span = []
    for m in matches:
        span = base_spans.get(id(m.base_block)) if m.base_block is not None else None
        matches_with_span.append((m, span))

    edits: List[MdEdit] = []
    for idx, (m, span) in enumerate(matches_with_span):
        if m.kind == 'equal':
            continue
        if m.kind == 'text_edit':
            if span is None:
                continue
            # code 特化：reason 改名、language 从基线继承
            if (isinstance(m.base_block, CodeBlock)
                    and isinstance(m.reviewed_block, CodeBlock)):
                if not m.reviewed_block.language and m.base_block.language:
                    m.reviewed_block.language = m.base_block.language
                new_md = _render_block_md(m.reviewed_block)
                edits.append(MdEdit(
                    target_line_range=span,
                    replacement=new_md,
                    reason='code_edit',
                    provenance=f'code block edit at line {span[0] + 1}',
                ))
                continue
            # table 特化：同形状走 cell_edit 精确替换
            if (isinstance(m.base_block, TableBlock)
                    and isinstance(m.reviewed_block, TableBlock)):
                bb, rb = m.base_block, m.reviewed_block
                if (len(bb.header) == len(rb.header)
                        and len(bb.rows) == len(rb.rows)):
                    start = span[0]
                    produced = False
                    if bb.header != rb.header:
                        new_line = '| ' + ' | '.join(rb.header) + ' |'
                        edits.append(MdEdit(
                            target_line_range=(start, start + 1),
                            replacement=new_line,
                            reason='cell_edit',
                            provenance=f'table header edit at line {start + 1}',
                        ))
                        produced = True
                    for k, (orow, nrow) in enumerate(zip(bb.rows, rb.rows)):
                        if orow != nrow:
                            # header 行占 span.start；分隔行 = start + 1；数据行 k = start + 2 + k
                            line_no = start + 2 + k
                            new_line = '| ' + ' | '.join(nrow) + ' |'
                            edits.append(MdEdit(
                                target_line_range=(line_no, line_no + 1),
                                replacement=new_line,
                                reason='cell_edit',
                                provenance=f'table cell edit at line {line_no + 1}',
                            ))
                            produced = True
                    if produced:
                        continue
                    # 完全相同 — 不产出 edit
                    continue
            new_md = _render_block_md(m.reviewed_block)
            edits.append(MdEdit(
                target_line_range=span,
                replacement=new_md,
                reason='text_edit',
                provenance=f'paragraph edit at line {span[0] + 1}',
            ))
        elif m.kind == 'struct_change':
            if span is None:
                continue
            new_md = _render_block_md(m.reviewed_block)
            edits.append(MdEdit(
                target_line_range=span,
                replacement=new_md,
                reason='struct_change',
                provenance=f'struct change at line {span[0] + 1}',
            ))
        elif m.kind == 'delete':
            if span is None:
                continue
            edits.append(MdEdit(
                target_line_range=span,
                replacement='',
                reason='delete',
                provenance=f'block deleted at line {span[0] + 1}',
            ))
        elif m.kind == 'insert':
            insert_at = _find_insertion_line(matches_with_span, idx)
            new_md = _render_block_md(m.reviewed_block)
            edits.append(MdEdit(
                target_line_range=(insert_at, insert_at),
                replacement=new_md,
                reason='insert',
                provenance=f'block inserted before line {insert_at + 1}',
            ))
    return edits


# ──────────────────────────────────────────────────────────
# Figure 处理（make_edits_with_media）
# ──────────────────────────────────────────────────────────

_FIGURE_FILENAME_RE = re.compile(r'img-([0-9a-f]{8,})\.png$', re.IGNORECASE)


def _figure_sha_from_reviewed(fb: FigureBlock) -> Optional[str]:
    """从 reviewed FigureBlock.path = '@media:<filename>:<sha>' 拿出 sha。"""
    if not fb.path.startswith('@media:'):
        return None
    parts = fb.path.split(':')
    if len(parts) != 3:
        return None
    return parts[2]


def _figure_sha_short_from_baseline(fb: FigureBlock) -> Optional[str]:
    """从 baseline 路径里 img-<sha8>.png 拿 8 位 sha。"""
    m = _FIGURE_FILENAME_RE.search(fb.path or '')
    return m.group(1) if m else None


def _maybe_persist_figure(sha: str, bytes_data: bytes,
                          image_dir: str = 'typora-user-images') -> str:
    """若 img-<sha8>.png 不存在则写入；返回相对路径（带 ./）。"""
    os.makedirs(image_dir, exist_ok=True)
    fn = f'img-{sha[:8]}.png'
    out_path = os.path.join(image_dir, fn)
    if not os.path.exists(out_path):
        with open(out_path, 'wb') as f:
            f.write(bytes_data)
    return f'./{image_dir}/{fn}'


def make_edits_with_media(baseline_md_text: str,
                          reviewed_blocks: List[Block],
                          media: dict) -> List[MdEdit]:
    """make_edits 的扩展：接收 media dict {sha -> bytes}，
    在 FigureBlock text_edit 时落盘新图并改 md path。"""
    edits = make_edits(baseline_md_text, reviewed_blocks)

    baseline_with_spans = parse_md_blocks_with_spans(baseline_md_text)
    base_blocks = [b for (b, _, _) in baseline_with_spans
                   if not isinstance(b, BlankBlock)]
    base_spans = {id(b): (s, e) for (b, s, e) in baseline_with_spans
                  if not isinstance(b, BlankBlock)}
    rev_blocks = [b for b in reviewed_blocks if not isinstance(b, BlankBlock)]
    matches = match_blocks(base_blocks, rev_blocks)

    # 构建 line_range -> edit 的索引以便覆盖
    edits_by_range = {(e.target_line_range, e.reason): e for e in edits}

    for m in matches:
        if m.kind not in ('text_edit', 'struct_change'):
            continue
        if not (isinstance(m.base_block, FigureBlock) and
                isinstance(m.reviewed_block, FigureBlock)):
            continue
        span = base_spans.get(id(m.base_block))
        if span is None:
            continue

        rev_sha = _figure_sha_from_reviewed(m.reviewed_block)
        base_sha_short = _figure_sha_short_from_baseline(m.base_block)

        # 前 8 位命中则视为同图：移除已有 edit（若有）
        if rev_sha and base_sha_short and rev_sha[:8] == base_sha_short:
            for key in list(edits_by_range.keys()):
                if key[0] == span:
                    edits_by_range.pop(key, None)
            continue

        # 落盘 + 产出 figure_replaced
        bytes_data = media.get(rev_sha) if rev_sha else None
        if bytes_data is None:
            new_path = m.reviewed_block.path if not m.reviewed_block.path.startswith('@media:') else ''
        else:
            new_path = _maybe_persist_figure(rev_sha, bytes_data)
        alt = m.reviewed_block.alt or m.base_block.alt
        new_md = f'![{alt}]({new_path})'

        for key in list(edits_by_range.keys()):
            if key[0] == span:
                edits_by_range.pop(key, None)
        edits_by_range[(span, 'figure_replaced')] = MdEdit(
            target_line_range=span,
            replacement=new_md,
            reason='figure_replaced',
            provenance=f'figure replace at line {span[0] + 1}, sha={rev_sha[:8] if rev_sha else "?"}',
        )

    # equation 特化：对 text_edit/struct_change 的 Equation→Equation 产占位 + 落盘片段
    attach_idx = 0
    for m in matches:
        if m.kind not in ('text_edit', 'struct_change'):
            continue
        if not (isinstance(m.base_block, EquationBlock) and
                isinstance(m.reviewed_block, EquationBlock)):
            continue
        span = base_spans.get(id(m.base_block))
        if span is None:
            continue
        attach_idx += 1
        _emit_formula_attachment(m.reviewed_block, attach_idx)
        new_md = (f'<!-- REVIEW: formula changed, '
                  f'see review/attachments/{attach_idx}.docx -->')
        for key in list(edits_by_range.keys()):
            if key[0] == span:
                edits_by_range.pop(key, None)
        edits_by_range[(span, 'formula_changed')] = MdEdit(
            target_line_range=span,
            replacement=new_md,
            reason='formula_changed',
            provenance=f'formula change at line {span[0] + 1}',
        )

    return list(edits_by_range.values())


# ──────────────────────────────────────────────────────────
# Comment 分流
# ──────────────────────────────────────────────────────────

EDIT_CONFIDENCE_THRESHOLD = 0.7


def make_edits_with_comments(baseline_md_text: str,
                             reviewed_blocks: List[Block],
                             media: dict,
                             classify_fn) -> List[MdEdit]:
    """make_edits_with_media 的进一步扩展：把每个 reviewed Block.comments
    经 classify_fn 分流为 comment_edit 或 comment_opinion MdEdit。

    classify_fn 接受 block_text / anchor_text / comment_body / md_context
    四个关键字参数，返回 dict（同 comment_classifier.classify）。
    """
    edits = list(make_edits_with_media(baseline_md_text, reviewed_blocks, media))

    # 重建 baseline span 映射用于定位 comment 锚点的行号
    baseline_with_spans = parse_md_blocks_with_spans(baseline_md_text)
    base_blocks = [b for (b, _, _) in baseline_with_spans
                   if not isinstance(b, BlankBlock)]
    base_spans = {id(b): (s, e) for (b, s, e) in baseline_with_spans
                  if not isinstance(b, BlankBlock)}
    rev_blocks_f = [b for b in reviewed_blocks if not isinstance(b, BlankBlock)]
    matches = match_blocks(base_blocks, rev_blocks_f)

    # 构造 reviewed_block -> base_span 的映射
    rev_to_span = {}
    for m in matches:
        if m.reviewed_block is not None and m.base_block is not None:
            span = base_spans.get(id(m.base_block))
            if span is not None:
                rev_to_span[id(m.reviewed_block)] = span

    lines = baseline_md_text.splitlines()
    for rb in rev_blocks_f:
        for c in getattr(rb, 'comments', []):
            span = rev_to_span.get(id(rb))
            if span is None:
                # 纯新增块的 comment；跳过（罕见）
                continue
            anchor_line = span[0]
            ctx_start = max(0, span[0] - 2)
            ctx_end = min(len(lines), span[1] + 2)
            md_context = '\n'.join(lines[ctx_start:ctx_end])

            result = classify_fn(
                block_text=getattr(rb, 'text', '') or getattr(rb, 'latex', '') or '',
                anchor_text=c.anchor_text,
                comment_body=c.text,
                md_context=md_context,
            )
            if (result.get('kind') == 'edit' and
                    result.get('confidence', 0) >= EDIT_CONFIDENCE_THRESHOLD and
                    result.get('new_text')):
                edits.append(MdEdit(
                    target_line_range=span,
                    replacement=result['new_text'],
                    reason='comment_edit',
                    provenance=(f'comment by {c.author} (conf={result["confidence"]:.2f}): '
                                f'"{c.text[:30]}"'),
                ))
            else:
                # 追加到锚点所在块末尾之后
                note = f'\n<!-- REVIEWER[{c.author}]: {c.text} -->'
                edits.append(MdEdit(
                    target_line_range=(span[1], span[1]),
                    replacement=note,
                    reason='comment_opinion',
                    provenance=f'comment by {c.author}',
                ))
    return edits


def _emit_formula_attachment(eq: EquationBlock, idx: int) -> None:
    """把 reviewed EquationBlock.raw（OMML XML 片段）包成最小 docx，存到
    review/attachments/<idx>.docx。若系统有 libreoffice，再转成 <idx>.png。"""
    out_dir = os.path.join('review', 'attachments')
    os.makedirs(out_dir, exist_ok=True)
    docx_path = os.path.join(out_dir, f'{idx}.docx')

    W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    M = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
    body = (
        f'<w:p><m:oMathPara xmlns:m="{M}">{eq.raw}</m:oMathPara></w:p>'
        if eq.raw.startswith('<m:oMath') else
        f'<w:p><w:r><w:t xml:space="preserve">{eq.latex}</w:t></w:r></w:p>'
    )
    import zipfile as _zf
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
          '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>')
    with _zf.ZipFile(docx_path, 'w', _zf.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', ct)
        z.writestr('_rels/.rels', rels)
        z.writestr('word/document.xml', doc)

    # 可选 libreoffice 转 png
    if _shutil.which('libreoffice') is not None:
        try:
            _subprocess.run(
                ['libreoffice', '--headless',
                 '--convert-to', 'png',
                 '--outdir', out_dir, docx_path],
                check=True, stdout=_subprocess.DEVNULL, stderr=_subprocess.PIPE,
                timeout=30,
            )
        except (_subprocess.CalledProcessError, _subprocess.TimeoutExpired):
            pass
