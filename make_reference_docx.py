#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 md2docx.py 使用的 Word 版式模板 reference_book.docx。

版式与《chapter2_new_v3_公式修订稿.docx》对齐（2026-08-23 用户要求）：
  * 正文：中文宋体、西文 Cambria，小四（12pt），无首行缩进，段后距 200；
  * 标题：中文黑体、西文 Calibri，加粗，主题色；
  * 代码：Consolas 11pt。

实现：取 pandoc 内置默认 reference.docx，将其 word/styles.xml 与
word/theme/theme1.xml 整体替换为 template/ 目录下从公式修订稿提取的
样式定义（styles_v3.xml / theme_v3.xml，已入库），重新打包。pandoc 按
样式名（Body Text、heading 1 等）识别 reference-doc 中的样式，样式 id
为数字不影响。reference_book.docx 本身不入库（*.docx 被 gitignore），
克隆仓库后运行本脚本一次即可。

注意：此版式与 RULE.md 第 27 条（首行缩进 2 字符、西文 Times New
Roman 5 号、代码 Courier New 小五）不一致，以用户 2026-08-23 指定的
公式修订稿版式为准；旧版式实现见 git 历史。
"""

import os
import subprocess
import tempfile
import zipfile

from md2docx import find_pandoc

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "reference_book.docx")
STYLES = os.path.join(HERE, "template", "styles_v3.xml")
THEME = os.path.join(HERE, "template", "theme_v3.xml")


def main() -> None:
    for p in (STYLES, THEME):
        if not os.path.isfile(p):
            raise SystemExit(f"错误：缺少模板资产 {p}（应随仓库提供）。")
    pandoc = find_pandoc()
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, "ref.docx")
        with open(base, "wb") as f:
            f.write(subprocess.run(
                [pandoc, "--print-default-data-file", "reference.docx"],
                capture_output=True, check=True).stdout)
        replace = {
            "word/styles.xml": open(STYLES, "rb").read(),
            "word/theme/theme1.xml": open(THEME, "rb").read(),
        }
        with zipfile.ZipFile(base) as zin, \
                zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                zout.writestr(item, replace.get(item.filename,
                                                zin.read(item.filename)))
    print(f"已生成 {OUT}")


if __name__ == "__main__":
    main()
