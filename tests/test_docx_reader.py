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
