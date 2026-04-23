"""docx_reader.py 的测试，fixtures 由 tests/fixtures/build_min_docx.py 就地构造。"""
from pathlib import Path

import pytest

from md_core import ParagraphBlock
from docx_reader import read_docx
from tests.fixtures.build_min_docx import write_docx, make_paragraph


def test_read_plain_paragraph(tmp_path):
    body = make_paragraph('这是一段纯文本。')
    docx = tmp_path / 'p.docx'
    write_docx(str(docx), body)

    blocks = read_docx(str(docx))
    paras = [b for b in blocks if isinstance(b, ParagraphBlock)]
    assert len(paras) == 1
    assert paras[0].text == '这是一段纯文本。'
    assert paras[0].revisions == []


def test_read_paragraph_with_ins_accepts_ins_in_text(tmp_path):
    """接受 ins：text 应包含 ins 的内容。"""
    body = make_paragraph('前缀XYZ后缀',
                          ins_spans=[(2, 5, '张三', '2026-04-23T00:00:00Z')])
    docx = tmp_path / 'p.docx'
    write_docx(str(docx), body)

    blocks = read_docx(str(docx))
    paras = [b for b in blocks if isinstance(b, ParagraphBlock)]
    p = paras[0]
    assert p.text == '前缀XYZ后缀'
    assert len(p.revisions) == 1
    r = p.revisions[0]
    assert r.kind == 'ins'
    assert r.text == 'XYZ'
    assert r.author == '张三'


def test_read_paragraph_with_del_excludes_del_from_text(tmp_path):
    """删除：text 应只含未删除部分；revisions 记录 del 的原文。"""
    # 构造时 text 是 "留下" 的部分；del 段是额外要标注为被删的 "掉" 字
    body_pieces = [
        '<w:p>',
        '<w:r><w:t xml:space="preserve">留下</w:t></w:r>',
        '<w:del w:id="2001" w:author="李四" w:date="2026-04-23T00:00:00Z">'
        '<w:r><w:delText xml:space="preserve">掉</w:delText></w:r>'
        '</w:del>',
        '<w:r><w:t xml:space="preserve">的文本</w:t></w:r>',
        '</w:p>',
    ]
    body = '\n'.join(body_pieces)
    docx = tmp_path / 'p.docx'
    write_docx(str(docx), body)

    blocks = read_docx(str(docx))
    paras = [b for b in blocks if isinstance(b, ParagraphBlock)]
    p = paras[0]
    assert p.text == '留下的文本'
    assert len(p.revisions) == 1
    r = p.revisions[0]
    assert r.kind == 'del'
    assert r.text == '掉'
    assert r.author == '李四'


def test_read_bad_zip_raises(tmp_path):
    bad = tmp_path / 'bad.docx'
    bad.write_text('not a zip', encoding='utf-8')
    from docx_reader import DocxReaderError
    with pytest.raises(DocxReaderError):
        read_docx(str(bad))


from md_core import HeadingBlock, ListBlock, CodeBlock
from tests.fixtures.build_min_docx import (
    make_heading, make_list_item, make_code_block,
)


def test_read_heading_levels(tmp_path):
    body = '\n'.join([
        make_heading(1, '章标题'),
        make_heading(2, '节标题'),
        make_heading(3, '小节'),
    ])
    docx = tmp_path / 'h.docx'
    write_docx(str(docx), body)
    blocks = read_docx(str(docx))
    hs = [b for b in blocks if isinstance(b, HeadingBlock)]
    assert len(hs) == 3
    assert (hs[0].level, hs[0].text) == (1, '章标题')
    assert (hs[1].level, hs[1].text) == (2, '节标题')
    assert (hs[2].level, hs[2].text) == (3, '小节')


def test_read_unordered_list_merges_adjacent_items(tmp_path):
    body = '\n'.join([
        make_list_item('第一条', ordered=False),
        make_list_item('第二条', ordered=False),
        make_list_item('第三条', ordered=False),
    ])
    docx = tmp_path / 'l.docx'
    write_docx(str(docx), body)
    blocks = read_docx(str(docx))
    lists = [b for b in blocks if isinstance(b, ListBlock)]
    assert len(lists) == 1
    assert lists[0].ordered is False
    assert lists[0].items == ['第一条', '第二条', '第三条']


def test_read_ordered_list(tmp_path):
    body = '\n'.join([
        make_list_item('A', ordered=True),
        make_list_item('B', ordered=True),
    ])
    docx = tmp_path / 'l.docx'
    write_docx(str(docx), body)
    blocks = read_docx(str(docx))
    lists = [b for b in blocks if isinstance(b, ListBlock)]
    assert len(lists) == 1
    assert lists[0].ordered is True
    assert lists[0].items == ['A', 'B']


def test_read_code_block_merges_adjacent_paragraphs(tmp_path):
    body = make_code_block([
        'def foo():',
        '    return 42',
        '',
    ])
    docx = tmp_path / 'c.docx'
    write_docx(str(docx), body)
    blocks = read_docx(str(docx))
    codes = [b for b in blocks if isinstance(b, CodeBlock)]
    assert len(codes) == 1
    assert codes[0].code == 'def foo():\n    return 42\n'


from md_core import TableBlock
from tests.fixtures.build_min_docx import make_table


def test_read_table_basic(tmp_path):
    body = make_table(
        header=['列A', '列B', '列C'],
        rows=[['1', '2', '3'], ['x', 'y', 'z']],
    )
    docx = tmp_path / 't.docx'
    write_docx(str(docx), body)
    blocks = read_docx(str(docx))
    tables = [b for b in blocks if isinstance(b, TableBlock)]
    assert len(tables) == 1
    t = tables[0]
    assert t.header == ['列A', '列B', '列C']
    assert t.rows == [['1', '2', '3'], ['x', 'y', 'z']]


def test_read_table_with_empty_cells(tmp_path):
    body = make_table(
        header=['A', 'B'],
        rows=[['', 'b']],
    )
    docx = tmp_path / 't.docx'
    write_docx(str(docx), body)
    blocks = read_docx(str(docx))
    tables = [b for b in blocks if isinstance(b, TableBlock)]
    assert len(tables) == 1
    assert tables[0].rows == [['', 'b']]


from md_core import EquationBlock
from tests.fixtures.build_min_docx import (
    make_equation_paragraph,
    SIMPLE_OMATH_X_EQ_1, SIMPLE_OMATH_X_EQ_2,
)


def test_read_block_equation(tmp_path):
    body = make_equation_paragraph(SIMPLE_OMATH_X_EQ_1)
    docx = tmp_path / 'e.docx'
    write_docx(str(docx), body)
    blocks = read_docx(str(docx))
    eqs = [b for b in blocks if isinstance(b, EquationBlock)]
    assert len(eqs) == 1
    # latex 字段暂时留作指纹载体：OMML 规范化字符串
    assert eqs[0].latex.startswith('@omml:')


def test_equation_fingerprint_distinguishes_different_omml(tmp_path):
    from docx_reader import equation_fingerprint
    import lxml.etree as ET
    f1 = equation_fingerprint(ET.fromstring(SIMPLE_OMATH_X_EQ_1))
    f2 = equation_fingerprint(ET.fromstring(SIMPLE_OMATH_X_EQ_2))
    assert len(f1) == 64  # sha256 hex
    assert f1 != f2


def test_equation_fingerprint_canonical_ignores_rpr_noise(tmp_path):
    """同一个公式但带了字体 rPr 属性，指纹应相同。"""
    from docx_reader import equation_fingerprint
    import lxml.etree as ET

    noisy = (
        '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'
        ' xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<m:r>'
        '<w:rPr><w:rFonts w:ascii="Cambria Math"/></w:rPr>'
        '<m:t xml:space="preserve">x=1</m:t>'
        '</m:r>'
        '</m:oMath>'
    )
    f_clean = equation_fingerprint(ET.fromstring(SIMPLE_OMATH_X_EQ_1))
    f_noisy = equation_fingerprint(ET.fromstring(noisy))
    assert f_clean == f_noisy


from md_core import FigureBlock
from tests.fixtures.build_min_docx import (
    make_figure_paragraph, make_doc_rels_with_image,
)

PNG_1x1 = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\x00'
    b'\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
)


def test_read_figure_with_media(tmp_path):
    body = make_figure_paragraph('rId7', alt='示意图')
    rels = make_doc_rels_with_image('rId7', 'sample.png')
    docx = tmp_path / 'f.docx'
    write_docx(str(docx), body,
               media={'sample.png': PNG_1x1},
               extra_rels=rels)
    blocks = read_docx(str(docx))
    figs = [b for b in blocks if isinstance(b, FigureBlock)]
    assert len(figs) == 1
    fb = figs[0]
    assert fb.alt == '示意图'
    # path 暂以 @media:<filename>:<sha256> 表示（docx_to_md 阶段再解析为真实 md 路径）
    assert fb.path.startswith('@media:sample.png:')
    assert len(fb.path.split(':')[-1]) == 64


def test_read_figure_missing_rel_falls_back_to_alt_only(tmp_path):
    # 没提供 rels 中对应的 id → path 空，alt 保留
    body = make_figure_paragraph('rIdX', alt='孤立图')
    docx = tmp_path / 'f.docx'
    write_docx(str(docx), body)  # 使用默认 rels（没有 rIdX 项）
    blocks = read_docx(str(docx))
    figs = [b for b in blocks if isinstance(b, FigureBlock)]
    assert len(figs) == 1
    assert figs[0].alt == '孤立图'
    assert figs[0].path == ''


from tests.fixtures.build_min_docx import (
    make_paragraph_with_comment, make_comments_xml,
)


def test_read_paragraph_with_one_comment(tmp_path):
    body = make_paragraph_with_comment(
        before='前段', anchor='此处', after='后段', comment_id=0)
    cxml = make_comments_xml([{
        'id': 0, 'author': '王五',
        'date': '2026-04-23T00:00:00Z', 'text': '这句不通',
    }])
    docx = tmp_path / 'c.docx'
    write_docx(str(docx), body, comments_xml=cxml)
    blocks = read_docx(str(docx))
    paras = [b for b in blocks if isinstance(b, ParagraphBlock)]
    assert len(paras) == 1
    p = paras[0]
    assert p.text == '前段此处后段'
    assert len(p.comments) == 1
    c = p.comments[0]
    assert c.comment_id == 0
    assert c.author == '王五'
    assert c.text == '这句不通'
    assert c.anchor_text == '此处'
    assert c.anchor_range == (2, 4)


def test_read_paragraph_with_pointless_comment_reference(tmp_path):
    """只有 commentReference、没有 range：anchor_range 指向同一点。"""
    body = (
        '<w:p>'
        '<w:r><w:t xml:space="preserve">一整段</w:t></w:r>'
        '<w:r><w:commentReference w:id="7"/></w:r>'
        '</w:p>'
    )
    cxml = make_comments_xml([{
        'id': 7, 'author': '赵六',
        'date': '2026-04-23T00:00:00Z', 'text': '通篇评论',
    }])
    docx = tmp_path / 'c.docx'
    write_docx(str(docx), body, comments_xml=cxml)
    blocks = read_docx(str(docx))
    p = [b for b in blocks if isinstance(b, ParagraphBlock)][0]
    assert len(p.comments) == 1
    c = p.comments[0]
    assert c.anchor_text == ''
    assert c.anchor_range == (3, 3)
