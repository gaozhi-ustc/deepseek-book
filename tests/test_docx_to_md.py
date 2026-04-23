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


from docx_to_md import make_edits


def test_make_edits_paragraph_text_edit():
    base_md = '这是第一段。\n\n这是第二段。\n'
    rev_blocks = [
        ParagraphBlock(text='这是第一段。', raw='这是第一段。'),
        ParagraphBlock(text='这是改过的第二段。', raw='这是改过的第二段。'),
    ]
    edits = make_edits(base_md, rev_blocks)
    # 只有一条 text_edit
    assert len(edits) == 1
    e = edits[0]
    assert e.reason == 'text_edit'
    assert '改过的第二段' in e.replacement
    # 第二段在 base_md 里的行号
    assert e.target_line_range == (2, 3)


def test_make_edits_heading_text_edit_preserves_level():
    base_md = '## 旧标题\n\n正文\n'
    rev_blocks = [
        HeadingBlock(level=2, text='新标题', raw='新标题'),
        ParagraphBlock(text='正文', raw='正文'),
    ]
    edits = make_edits(base_md, rev_blocks)
    assert len(edits) == 1
    assert edits[0].reason == 'text_edit'
    assert edits[0].replacement == '## 新标题'


def test_make_edits_heading_level_change():
    base_md = '## 同文本\n'
    rev_blocks = [HeadingBlock(level=3, text='同文本', raw='同文本')]
    edits = make_edits(base_md, rev_blocks)
    assert len(edits) == 1
    # 级别改到 ### 同文本
    assert edits[0].replacement == '### 同文本'


def test_make_edits_equal_produces_no_edits():
    base_md = '第一段。\n\n第二段。\n'
    rev_blocks = [
        ParagraphBlock(text='第一段。', raw='第一段。'),
        ParagraphBlock(text='第二段。', raw='第二段。'),
    ]
    assert make_edits(base_md, rev_blocks) == []


def test_make_edits_insert_inserts_after_preceding_equal():
    base_md = '段一。\n\n段二。\n'
    rev_blocks = [
        ParagraphBlock(text='段一。', raw='段一。'),
        ParagraphBlock(text='新插入段。', raw='新插入段。'),
        ParagraphBlock(text='段二。', raw='段二。'),
    ]
    edits = make_edits(base_md, rev_blocks)
    assert len(edits) == 1
    e = edits[0]
    assert e.reason == 'insert'
    # 插在"段一。"后（位置索引 1 之后，且保持 blank 行）
    assert e.target_line_range[0] == 1
    assert e.target_line_range[1] == 1  # 插入不删除
    assert '新插入段。' in e.replacement


def test_make_edits_delete_removes_block_lines():
    base_md = '段一。\n\n要删。\n\n段二。\n'
    rev_blocks = [
        ParagraphBlock(text='段一。', raw='段一。'),
        ParagraphBlock(text='段二。', raw='段二。'),
    ]
    edits = make_edits(base_md, rev_blocks)
    assert len(edits) == 1
    e = edits[0]
    assert e.reason == 'delete'
    assert e.replacement == ''
    assert e.target_line_range == (2, 3)  # "要删。"一行


def test_make_edits_list_item_changed():
    base_md = '- 第一\n- 第二\n- 第三\n\n后文\n'
    rev_blocks = [
        ListBlock(items=['第一', '第二改', '第三'], ordered=False, raw=''),
        ParagraphBlock(text='后文', raw='后文'),
    ]
    edits = make_edits(base_md, rev_blocks)
    # 简化策略：list 整块替换
    list_edits = [e for e in edits if e.reason in ('text_edit', 'list_edit')]
    assert len(list_edits) == 1
    assert '第二改' in list_edits[0].replacement
    assert '第一' in list_edits[0].replacement
    assert '第三' in list_edits[0].replacement


def test_make_edits_ordered_list_changes_to_unordered():
    base_md = '1. A\n2. B\n'
    rev_blocks = [
        ListBlock(items=['A', 'B'], ordered=False, raw=''),
    ]
    edits = make_edits(base_md, rev_blocks)
    assert len(edits) == 1
    assert edits[0].reason in ('struct_change', 'text_edit')
    assert edits[0].replacement.startswith('- A')


def test_make_edits_code_changed():
    base_md = '```python\nprint(1)\n```\n'
    rev_blocks = [
        CodeBlock(code='print(2)', language='python', title='', raw=''),
    ]
    edits = make_edits(base_md, rev_blocks)
    assert len(edits) == 1
    assert edits[0].reason == 'code_edit'
    assert 'print(2)' in edits[0].replacement


def test_make_edits_code_language_preserved_from_baseline():
    """如果 reviewed code 没有 language（docx_reader 读不出），从基线继承。"""
    base_md = '```python\nprint(1)\n```\n'
    rev_blocks = [
        CodeBlock(code='print(2)', language='', title='', raw=''),
    ]
    edits = make_edits(base_md, rev_blocks)
    assert '```python' in edits[0].replacement


def test_make_edits_table_cell_changes_same_shape():
    base_md = (
        '| A | B | C |\n'
        '|---|---|---|\n'
        '| 1 | 2 | 3 |\n'
        '| 4 | 5 | 6 |\n'
    )
    rev_blocks = [
        TableBlock(header=['A', 'B', 'C'],
                   rows=[['1', 'X', '3'], ['4', '5', 'Y']],
                   caption='', raw=''),
    ]
    edits = make_edits(base_md, rev_blocks)
    # 两个 cell 改动 → 两条 cell_edit
    cell_edits = [e for e in edits if e.reason == 'cell_edit']
    assert len(cell_edits) == 2
    # 第一条改在基线第 3 行（0-index=2），replacement 覆盖整行
    first = [e for e in cell_edits if e.target_line_range == (2, 3)][0]
    assert first.replacement == '| 1 | X | 3 |'
    second = [e for e in cell_edits if e.target_line_range == (3, 4)][0]
    assert second.replacement == '| 4 | 5 | Y |'


def test_make_edits_table_struct_change_replaces_whole_block():
    base_md = (
        '| A | B |\n'
        '|---|---|\n'
        '| 1 | 2 |\n'
    )
    rev_blocks = [
        TableBlock(header=['A', 'B', 'C'],
                   rows=[['1', '2', '3']], caption='', raw=''),
    ]
    edits = make_edits(base_md, rev_blocks)
    assert len(edits) == 1
    assert edits[0].reason == 'struct_change'
    assert '| A | B | C |' in edits[0].replacement
