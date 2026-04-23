"""确保在 md_core.Block 追加 revisions/comments 字段后，
所有历史构造点（md_core / md_formatter / md_diff_docx 内部）仍能不传新字段而成立，
且新字段默认为空 list。"""

from md_core import (
    HeadingBlock, ParagraphBlock, EquationBlock,
    TableBlock, CodeBlock, FigureBlock, ListBlock, BlankBlock,
    Revision, Comment,
)


def test_paragraph_block_backwards_compatible():
    b = ParagraphBlock(text='hello', raw='hello')
    assert b.text == 'hello'
    assert b.revisions == []
    assert b.comments == []


def test_heading_block_backwards_compatible():
    b = HeadingBlock(level=2, text='标题', raw='## 标题')
    assert b.level == 2
    assert b.revisions == []
    assert b.comments == []


def test_all_blocks_have_revisions_and_comments():
    blocks = [
        HeadingBlock(level=1, text='a', raw='# a'),
        ParagraphBlock(text='p', raw='p'),
        EquationBlock(latex='x=1', raw='$$x=1$$'),
        TableBlock(header=['A'], rows=[['1']], caption='', raw=''),
        CodeBlock(code='x=1', language='python', title='', raw=''),
        FigureBlock(alt='alt', path='x.png', caption='', raw=''),
        ListBlock(items=['a', 'b'], ordered=False, raw=''),
        BlankBlock(),
    ]
    for b in blocks:
        assert hasattr(b, 'revisions')
        assert hasattr(b, 'comments')
        assert b.revisions == []
        assert b.comments == []


def test_revision_dataclass_shape():
    r = Revision(kind='ins', text='new', author='张三',
                 date='2026-04-23T10:00:00Z', rev_id=1)
    assert r.kind == 'ins'
    assert r.text == 'new'
    assert r.author == '张三'


def test_comment_dataclass_shape():
    c = Comment(comment_id=0, author='李四',
                date='2026-04-23T10:00:00Z',
                text='这句不通', anchor_text='此处',
                anchor_range=(0, 2))
    assert c.comment_id == 0
    assert c.anchor_range == (0, 2)


def test_blocks_accept_revisions_and_comments_kwargs():
    r = Revision(kind='del', text='old', author='a', date='d', rev_id=1)
    c = Comment(comment_id=0, author='a', date='d',
                text='b', anchor_text='b', anchor_range=(0, 1))
    b = ParagraphBlock(text='t', raw='t', revisions=[r], comments=[c])
    assert b.revisions == [r]
    assert b.comments == [c]
