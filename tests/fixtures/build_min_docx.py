"""造带精确 OOXML 结构（track changes / comments / 表格 / 公式等）的
最小 docx 供单测使用。不是给终端用户的。

函数按『造一个含特定元素的 docx』粒度提供，测试里直接调用。
"""
import zipfile

W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


_MIN_CONTENT_TYPES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>
</Types>
'''

_MIN_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
'''

_MIN_DOC_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>
</Relationships>
'''


def write_docx(path: str, document_xml_body: str,
               comments_xml: str | None = None,
               media: dict | None = None,
               extra_rels: str | None = None) -> None:
    """
    document_xml_body 直接是 <w:body> 内部的 XML（不含 <w:document> 外壳）。
    comments_xml 为完整 <w:comments>...</w:comments>，可为 None。
    media: dict[内部路径 → bytes]
    """
    document_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body>
{document_xml_body}
  </w:body>
</w:document>'''

    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', _MIN_CONTENT_TYPES)
        z.writestr('_rels/.rels', _MIN_RELS)
        z.writestr('word/_rels/document.xml.rels',
                   extra_rels or _MIN_DOC_RELS)
        z.writestr('word/document.xml', document_xml)
        if comments_xml is not None:
            z.writestr('word/comments.xml', comments_xml)
        if media:
            for subpath, data in media.items():
                z.writestr(f'word/media/{subpath}', data)


def make_paragraph(text: str, *,
                   ins_spans: list[tuple[int, int, str, str]] | None = None,
                   del_spans: list[tuple[int, int, str, str]] | None = None) -> str:
    """
    构造一个 <w:p>，text 为接受全部 ins / 全部 del 仍保留状态后的
    "最终"文本；ins_spans / del_spans 是基于 text 字符偏移的标注列表
    [(start, end, author, date)]。

    输出的 runs 会按顺序穿插 <w:r>（普通）/ <w:ins>（整段）/ <w:del>（整段删除）。
    del_spans 的文本从 text 切片；删除的部分不出现在 "accepted" 可见文本里，
    但此函数接受的 text 是已经排除 del 的"visible"文本 — 参见下例。

    为简化：两种 spans 互斥，不重叠。
    """
    spans = []
    for s, e, a, d in (ins_spans or []):
        spans.append((s, e, 'ins', a, d))
    for s, e, a, d in (del_spans or []):
        spans.append((s, e, 'del', a, d))
    spans.sort()

    # 把 text 按 spans 切成段；text 里不包含 del 的文本（del 是单独插回）
    parts = []
    pos = 0
    for (s, e, kind, a, d) in spans:
        if pos < s:
            parts.append(('plain', text[pos:s], None, None))
        parts.append((kind, text[s:e], a, d))
        pos = e
    if pos < len(text):
        parts.append(('plain', text[pos:], None, None))

    out = ['<w:p>']
    rev_id = 1000
    for (kind, t, a, d) in parts:
        if kind == 'plain':
            out.append(f'<w:r><w:t xml:space="preserve">{t}</w:t></w:r>')
        elif kind == 'ins':
            rev_id += 1
            out.append(
                f'<w:ins w:id="{rev_id}" w:author="{a}" w:date="{d}">'
                f'<w:r><w:t xml:space="preserve">{t}</w:t></w:r>'
                '</w:ins>')
        elif kind == 'del':
            rev_id += 1
            out.append(
                f'<w:del w:id="{rev_id}" w:author="{a}" w:date="{d}">'
                f'<w:r><w:delText xml:space="preserve">{t}</w:delText></w:r>'
                '</w:del>')
    out.append('</w:p>')
    return '\n'.join(out)


def make_heading(level: int, text: str) -> str:
    return (f'<w:p><w:pPr><w:pStyle w:val="Heading{level}"/></w:pPr>'
            f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>')


def make_list_item(text: str, *, ordered: bool = False, num_id: int = 1) -> str:
    """w:numPr 引用 w:numId — 我们用约定 numId=1 为无序，numId=2 为有序，
    上层只需读 numId 判断是否是列表。"""
    nid = 1 if not ordered else 2
    _ = num_id
    return (f'<w:p><w:pPr><w:numPr>'
            f'<w:ilvl w:val="0"/><w:numId w:val="{nid}"/></w:numPr></w:pPr>'
            f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>')


def make_code_block(code_lines: list[str]) -> str:
    """约定：pStyle=Code / HTMLPreformatted / Courier 之一即视作 code；
    我们这里用 pStyle="Code"，docx_reader 会识别。
    多行会产生多个 <w:p>。"""
    paras = []
    for line in code_lines:
        paras.append(
            f'<w:p><w:pPr><w:pStyle w:val="Code"/></w:pPr>'
            f'<w:r><w:rPr><w:rFonts w:ascii="Courier New"/></w:rPr>'
            f'<w:t xml:space="preserve">{line}</w:t></w:r></w:p>'
        )
    return '\n'.join(paras)


def make_table(header: list[str], rows: list[list[str]]) -> str:
    def cell(text):
        return (f'<w:tc><w:p><w:r><w:t xml:space="preserve">{text}'
                '</w:t></w:r></w:p></w:tc>')
    all_rows = [header] + rows
    out = ['<w:tbl>']
    for row in all_rows:
        out.append('<w:tr>')
        for c in row:
            out.append(cell(c))
        out.append('</w:tr>')
    out.append('</w:tbl>')
    return '\n'.join(out)
