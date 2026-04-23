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
