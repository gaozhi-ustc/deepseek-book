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


def test_make_edits_figure_replace_writes_new_file(tmp_path, monkeypatch):
    from docx_to_md import make_edits_with_media

    base_md = '![旧](./typora-user-images/old.png)\n\n正文。\n'

    new_bytes = b'fake png bytes v2'
    new_sha = hashlib.sha256(new_bytes).hexdigest()
    short = new_sha[:8]

    rev_blocks = [
        FigureBlock(alt='新', path=f'@media:image7.png:{new_sha}',
                    caption='', raw=''),
        ParagraphBlock(text='正文。', raw='正文。'),
    ]
    media = {new_sha: new_bytes}

    monkeypatch.chdir(tmp_path)
    (tmp_path / 'typora-user-images').mkdir()

    edits = make_edits_with_media(base_md, rev_blocks, media)

    figure_edits = [e for e in edits if e.reason == 'figure_replaced']
    assert len(figure_edits) == 1
    e = figure_edits[0]
    assert e.target_line_range == (0, 1)
    assert f'typora-user-images/img-{short}.png' in e.replacement
    # 文件应已写入
    out_file = tmp_path / 'typora-user-images' / f'img-{short}.png'
    assert out_file.exists()
    assert out_file.read_bytes() == new_bytes


def test_make_edits_figure_same_sha_no_change(tmp_path, monkeypatch):
    """当 reviewed FigureBlock.path 中 sha 的前 8 位与 baseline 的
    img-<sha8>.png 一致，视为同图，不产出 figure_replaced。"""
    from docx_to_md import make_edits_with_media
    base_md = '![alt](./typora-user-images/img-aaaaaaaa.png)\n'
    sha = 'a' * 64  # 前 8 位 "aaaaaaaa" 等同于文件名
    rev_blocks = [
        FigureBlock(alt='alt',
                    path=f'@media:image1.png:{sha}',
                    caption='', raw=''),
    ]
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'typora-user-images').mkdir()
    edits = make_edits_with_media(base_md, rev_blocks, {sha: b'x'})
    # 期望不产出 figure_replaced
    assert not any(e.reason == 'figure_replaced' for e in edits)


def test_make_edits_equation_changed_emits_placeholder(tmp_path, monkeypatch):
    from docx_to_md import make_edits_with_media

    base_md = '正文。\n\n$$a + b = c$$\n\n后文。\n'
    # reviewed：指纹不同
    rev_blocks = [
        ParagraphBlock(text='正文。', raw='正文。'),
        EquationBlock(latex='@omml:ffffffffffffffff' + 'f' * 48,
                      raw='<m:oMath/>'),
        ParagraphBlock(text='后文。', raw='后文。'),
    ]
    monkeypatch.chdir(tmp_path)
    edits = make_edits_with_media(base_md, rev_blocks, media={})

    eq_edits = [e for e in edits if e.reason == 'formula_changed']
    assert len(eq_edits) == 1
    e = eq_edits[0]
    assert '<!-- REVIEW: formula changed' in e.replacement
    # attachments 目录下应有片段 docx（不依赖 libreoffice）
    assert (tmp_path / 'review' / 'attachments').exists()
    docx_files = list((tmp_path / 'review' / 'attachments').glob('*.docx'))
    assert len(docx_files) == 1


def test_make_edits_equation_same_fingerprint_no_edit(tmp_path, monkeypatch):
    from docx_to_md import make_edits_with_media
    base_md = '$$x=1$$\n'
    rev_blocks = [EquationBlock(latex='x=1', raw='')]
    monkeypatch.chdir(tmp_path)
    edits = make_edits_with_media(base_md, rev_blocks, media={})
    # match_blocks 按 _block_key='EQ:x=1' 对相等
    assert edits == []


def _mock_classifier_edit(new_text: str, conf: float):
    def fn(**kwargs):
        return {'kind': 'edit', 'new_text': new_text,
                'confidence': conf, 'reasoning': '-'}
    return fn


def _mock_classifier_opinion():
    def fn(**kwargs):
        return {'kind': 'opinion', 'new_text': None,
                'confidence': 0.5, 'reasoning': 'discussion'}
    return fn


def test_comment_edit_high_conf_becomes_text_edit(tmp_path, monkeypatch):
    from docx_to_md import make_edits_with_comments
    base_md = '前者发生在预训练阶段。\n'
    rev_block = ParagraphBlock(
        text='前者发生在预训练阶段。', raw='前者发生在预训练阶段。',
        comments=[Comment(comment_id=0, author='审校者',
                          date='2026-04-23T00:00:00Z',
                          text='改成：前者出现于预训练阶段。',
                          anchor_text='前者发生在预训练阶段。',
                          anchor_range=(0, 12))],
    )
    monkeypatch.chdir(tmp_path)
    edits = make_edits_with_comments(
        base_md, [rev_block],
        media={},
        classify_fn=_mock_classifier_edit('前者出现于预训练阶段。', 0.9),
    )
    ces = [e for e in edits if e.reason == 'comment_edit']
    assert len(ces) == 1
    assert ces[0].replacement == '前者出现于预训练阶段。'


def test_comment_edit_low_conf_becomes_opinion(tmp_path, monkeypatch):
    from docx_to_md import make_edits_with_comments
    base_md = '前者发生在预训练阶段。\n'
    rev_block = ParagraphBlock(
        text='前者发生在预训练阶段。', raw='前者发生在预训练阶段。',
        comments=[Comment(comment_id=0, author='审校者',
                          date='2026-04-23T00:00:00Z',
                          text='也许可以改一下？',
                          anchor_text='前者',
                          anchor_range=(0, 2))],
    )
    monkeypatch.chdir(tmp_path)
    edits = make_edits_with_comments(
        base_md, [rev_block], media={},
        classify_fn=_mock_classifier_edit('XXX', 0.5),  # conf < 0.7
    )
    cos = [e for e in edits if e.reason == 'comment_opinion']
    assert len(cos) == 1
    assert '<!-- REVIEWER[审校者]:' in cos[0].replacement


def test_comment_pure_opinion_becomes_opinion(tmp_path, monkeypatch):
    from docx_to_md import make_edits_with_comments
    base_md = '正文。\n'
    rev_block = ParagraphBlock(
        text='正文。', raw='正文。',
        comments=[Comment(comment_id=0, author='张三',
                          date='2026-04-23T00:00:00Z',
                          text='这段可以更精简',
                          anchor_text='正文。', anchor_range=(0, 3))],
    )
    monkeypatch.chdir(tmp_path)
    edits = make_edits_with_comments(
        base_md, [rev_block], media={},
        classify_fn=_mock_classifier_opinion(),
    )
    cos = [e for e in edits if e.reason == 'comment_opinion']
    assert len(cos) == 1
    assert '张三' in cos[0].replacement


def test_apply_edits_replace_single_line():
    from docx_to_md import apply_edits_to_md
    base = 'A\nB\nC\n'
    edits = [MdEdit(target_line_range=(1, 2),
                    replacement='BB', reason='text_edit')]
    new_text, warnings = apply_edits_to_md(base, edits)
    assert new_text == 'A\nBB\nC\n'
    assert warnings == []


def test_apply_edits_multiple_in_order_descending():
    from docx_to_md import apply_edits_to_md
    base = 'A\nB\nC\nD\n'
    edits = [
        MdEdit(target_line_range=(0, 1), replacement='A1', reason='text_edit'),
        MdEdit(target_line_range=(3, 4), replacement='D1', reason='text_edit'),
    ]
    new_text, warnings = apply_edits_to_md(base, edits)
    assert new_text == 'A1\nB\nC\nD1\n'
    assert warnings == []


def test_apply_edits_delete():
    from docx_to_md import apply_edits_to_md
    base = 'A\nB\nC\n'
    edits = [MdEdit(target_line_range=(1, 2), replacement='', reason='delete')]
    new_text, _ = apply_edits_to_md(base, edits)
    assert new_text == 'A\nC\n'


def test_apply_edits_insert():
    from docx_to_md import apply_edits_to_md
    base = 'A\nB\n'
    edits = [MdEdit(target_line_range=(1, 1),
                    replacement='NEW', reason='insert')]
    new_text, _ = apply_edits_to_md(base, edits)
    assert new_text == 'A\nNEW\nB\n'


def test_apply_edits_conflict_warns_and_second_wins():
    from docx_to_md import apply_edits_to_md
    base = 'A\nB\nC\n'
    edits = [
        MdEdit(target_line_range=(1, 2), replacement='X',
               reason='text_edit', provenance='first'),
        MdEdit(target_line_range=(1, 2), replacement='Y',
               reason='text_edit', provenance='second'),
    ]
    new_text, warnings = apply_edits_to_md(base, edits)
    # 后者（second）覆盖前者
    assert new_text == 'A\nY\nC\n'
    assert len(warnings) == 1
    assert 'first' in warnings[0]


def test_apply_edits_opinion_appends_newline():
    from docx_to_md import apply_edits_to_md
    base = 'A\nB\n'
    edits = [MdEdit(target_line_range=(1, 1),
                    replacement='\n<!-- REVIEWER: x -->',
                    reason='comment_opinion')]
    new_text, _ = apply_edits_to_md(base, edits)
    assert new_text == 'A\n\n<!-- REVIEWER: x -->\nB\n'


def test_render_commit_message_summary_counts():
    from docx_to_md import render_commit_message
    edits = [
        MdEdit(target_line_range=(0, 1), replacement='A', reason='text_edit',
               provenance='p1'),
        MdEdit(target_line_range=(3, 4), replacement='B', reason='text_edit',
               provenance='p2'),
        MdEdit(target_line_range=(5, 5),
               replacement='\n<!-- REVIEWER[x]: y -->',
               reason='comment_opinion', provenance='op'),
        MdEdit(target_line_range=(7, 8), replacement='', reason='delete',
               provenance='d'),
        MdEdit(target_line_range=(9, 10), replacement='C', reason='cell_edit',
               provenance='ce'),
    ]
    msg = render_commit_message(
        edits=edits, warnings=[],
        reviewer='张三', docx_filename='chapter_abc1234.docx',
        base_sha='abcdef1234567890' * 2 + 'abcd',
        baseline_source='metadata',
    )
    first_line = msg.splitlines()[0]
    assert '2 处文本修改' in first_line or '4 处文本修改' in first_line
    assert '1 条意见' in first_line
    assert 'chapter_abc1234.docx' in msg
    assert 'abcdef1' in msg  # short sha
    assert '基线来源: metadata' in msg
    assert 'Co-Authored-By: md-docx-bridge' in msg


def test_render_commit_message_with_warnings():
    from docx_to_md import render_commit_message
    msg = render_commit_message(
        edits=[MdEdit(target_line_range=(0, 1), replacement='x',
                      reason='text_edit', provenance='p')],
        warnings=['conflict: edit X overlaps Y'],
        reviewer='Z', docx_filename='a.docx',
        base_sha='a' * 40, baseline_source='cli',
    )
    assert 'WARNING' in msg or '警告' in msg
    assert 'conflict: edit X overlaps Y' in msg
