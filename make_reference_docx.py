#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 md2docx.py 使用的 Word 版式模板 reference_book.docx。

版式依据编辑要求（RULE.md 第 27 条）：
  * 正文段落首行缩进 2 字符；
  * 正文西文 Times New Roman、中文宋体，字号 5 号（10.5pt）；
  * 代码 Courier New，字号小五（9pt）。

原理：取 pandoc 内置默认 reference.docx，改写其中 word/styles.xml 的
Normal / Body Text / Verbatim Char 样式后重新打包。*.docx 不入库，
克隆仓库后运行本脚本一次即可。
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

from md2docx import find_pandoc

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reference_book.docx")


def patch_styles(xml: str) -> str:
    # Normal：西文 Times New Roman、中文宋体、5号（21 半磅）
    xml, n = re.subn(
        r'(<w:style w:type="paragraph" w:default="1" w:styleId="Normal">\s*'
        r'<w:name w:val="Normal" />\s*<w:qFormat />)',
        r'\1\n    <w:rPr>\n'
        r'      <w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="宋体" />\n'
        r'      <w:sz w:val="21" />\n      <w:szCs w:val="21" />\n    </w:rPr>',
        xml)
    assert n == 1, "Normal 样式改写失败"

    # Body Text：首行缩进 2 字符（First Paragraph 基于它，自动继承）
    xml, n = re.subn(
        r'(<w:style w:type="paragraph" w:styleId="BodyText">.*?'
        r'<w:spacing w:before="180" w:after="180" />)',
        r'\1\n      <w:ind w:firstLineChars="200" w:firstLine="420" />',
        xml, flags=re.S)
    assert n == 1, "BodyText 样式改写失败"

    # Verbatim Char（行内代码与代码块字体来源）：Courier New 小五（18 半磅）
    xml, n = re.subn(
        r'<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" />\s*<w:sz w:val="22" />',
        '<w:rFonts w:ascii="Courier New" w:hAnsi="Courier New" />\n      <w:sz w:val="18" />',
        xml)
    assert n >= 1, "VerbatimChar 样式改写失败"
    return xml


def main() -> None:
    pandoc = find_pandoc()
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, "ref.docx")
        with open(base, "wb") as f:
            f.write(subprocess.run(
                [pandoc, "--print-default-data-file", "reference.docx"],
                capture_output=True, check=True).stdout)
        with zipfile.ZipFile(base) as zin:
            styles = patch_styles(zin.read("word/styles.xml").decode("utf-8"))
            with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = (styles.encode("utf-8") if item.filename == "word/styles.xml"
                            else zin.read(item.filename))
                    zout.writestr(item, data)
    print(f"已生成 {OUT}")


if __name__ == "__main__":
    main()
