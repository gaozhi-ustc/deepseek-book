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

def match_blocks(base: List[Block], rev: List[Block]) -> List[BlockMatch]:
    """两轮块匹配。
    第一轮：SequenceMatcher on _block_key → equal/delete/insert/replace opcodes
    第二轮：对 replace 段里每对块做 ratio；
             ratio >= 0.5 → text_edit 或 struct_change
             ratio <  0.5 → 拆成 delete + insert
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
                matches.append(BlockMatch(a, b, 'equal'))
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
