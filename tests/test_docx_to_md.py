"""docx_to_md.py 块匹配与分级 MdEdit 生成测试。"""
import hashlib
from unittest.mock import MagicMock

import pytest

from md_core import (
    ParagraphBlock, HeadingBlock, EquationBlock,
    TableBlock, CodeBlock, FigureBlock, ListBlock,
    Comment,
)
from docx_to_md import match_blocks, BlockMatch, MdEdit


def _p(t): return ParagraphBlock(text=t, raw=t)


def test_match_blocks_all_equal():
    base = [_p('A'), _p('B'), _p('C')]
    rev  = [_p('A'), _p('B'), _p('C')]
    matches = match_blocks(base, rev)
    assert len(matches) == 3
    assert all(m.kind == 'equal' for m in matches)


def test_match_blocks_text_edit_high_similarity():
    base = [_p('前者发生在预训练阶段。')]
    rev  = [_p('前者出现于预训练阶段。')]
    m = match_blocks(base, rev)
    assert len(m) == 1
    assert m[0].kind == 'text_edit'
    assert m[0].base_block.text == '前者发生在预训练阶段。'
    assert m[0].reviewed_block.text == '前者出现于预训练阶段。'


def test_match_blocks_low_similarity_becomes_delete_insert():
    base = [_p('完全不同的一段 A')]
    rev  = [_p('XYZ 另起的一段内容')]
    m = match_blocks(base, rev)
    # 粗匹配为 replace，ratio < 0.5 故拆成 delete + insert
    kinds = [x.kind for x in m]
    assert 'delete' in kinds and 'insert' in kinds


def test_match_blocks_pure_insert():
    base = [_p('A')]
    rev  = [_p('A'), _p('B')]
    m = match_blocks(base, rev)
    assert m[0].kind == 'equal'
    assert m[1].kind == 'insert' and m[1].reviewed_block.text == 'B'


def test_match_blocks_pure_delete():
    base = [_p('A'), _p('B')]
    rev  = [_p('A')]
    m = match_blocks(base, rev)
    assert m[0].kind == 'equal'
    assert m[1].kind == 'delete' and m[1].base_block.text == 'B'


def test_match_blocks_struct_change_heading_level():
    base = [HeadingBlock(level=2, text='同文本', raw='## 同文本')]
    rev  = [HeadingBlock(level=3, text='同文本', raw='### 同文本')]
    m = match_blocks(base, rev)
    # heading 级别变 但文本同 → text_edit（保 level 变化）
    assert len(m) == 1
    assert m[0].kind == 'text_edit'


def test_match_blocks_table_shape_changed():
    base = [TableBlock(header=['A', 'B'], rows=[['1', '2']], caption='', raw='')]
    rev  = [TableBlock(header=['A', 'B', 'C'], rows=[['1', '2', '3']], caption='', raw='')]
    m = match_blocks(base, rev)
    assert len(m) == 1
    assert m[0].kind == 'struct_change'
