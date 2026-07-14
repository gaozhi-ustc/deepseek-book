#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""md2docx.py —— 把书稿 Markdown 转为 Word docx，重点保证 LaTeX 公式转为 Word 原生公式。

用法：
    python3 md2docx.py                     # 默认转换 chapter2_new.md 与 chapter3_new.md
    python3 md2docx.py 文件1.md [文件2.md]  # 转换指定文件，输出同名 .docx

原理与要点：
  * 使用 pandoc 的 gfm+tex_math_dollars 读取器：$...$ 与 $$...$$ 中的 LaTeX
    公式被解析为数学节点，docx 写入器将其输出为 Word 原生 OMML 公式
    （Office Math Markup Language，即 Word 内置公式编辑器格式，可直接双击编辑），
    而非图片或纯文本。
  * 转换后自动校验：统计源文件中的公式数（行间 $$ 块 + 行内 $ 对），
    与 docx 内部 word/document.xml 的 <m:oMath> 公式节点数比对，
    数目不符时给出警告，防止公式被悄悄转成纯文本。
  * 图片按相对路径（如 pic/2-1.png）嵌入 docx；Markdown 脚注转为 Word 页脚注。

依赖：pandoc ≥ 2.19（脚本按 PANDOC 环境变量 → PATH → ~/.local/bin/pandoc 顺序查找）。
"""

import os
import re
import shutil
import subprocess
import sys
import zipfile


def find_pandoc() -> str:
    cand = [os.environ.get("PANDOC"), shutil.which("pandoc"),
            os.path.expanduser("~/.local/bin/pandoc")]
    for p in cand:
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    sys.exit("错误：找不到 pandoc。请安装 pandoc（或设置 PANDOC 环境变量指向其二进制）。\n"
             "静态二进制下载：https://github.com/jgm/pandoc/releases")


def count_source_math(md_text: str) -> tuple[int, int]:
    """返回 (行间公式块数, 行内公式数)。转义的 \\$ 不计。"""
    # 去掉代码块与行内代码，避免误计
    text = re.sub(r"```.*?```", "", md_text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", "", text)
    text = text.replace(r"\$", "")          # 转义美元符是字面字符，不是公式定界
    display = re.findall(r"\$\$(.+?)\$\$", text, flags=re.S)
    text = re.sub(r"\$\$.+?\$\$", "", text, flags=re.S)
    inline = re.findall(r"\$[^$\n]+\$", text)
    return len(display), len(inline)


def count_docx_math(docx_path: str) -> tuple[int, int]:
    """返回 docx 中 (行间 OMML 公式数, OMML 公式总数)。"""
    with zipfile.ZipFile(docx_path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    # 注意区分 <m:oMathPara> 与其内部属性节点 <m:oMathParaPr>
    n_para = len(re.findall(r"<m:oMathPara[ >]", xml))
    n_math = len(re.findall(r"<m:oMath[ >]", xml))
    return n_para, n_math


def convert(pandoc: str, md_path: str, out_path: str | None = None) -> bool:
    docx_path = out_path or (os.path.splitext(md_path)[0] + ".docx")
    src_dir = os.path.dirname(os.path.abspath(md_path)) or "."
    cmd = [
        pandoc, md_path,
        "-f", "gfm+tex_math_dollars",   # 关键：识别 $...$ / $$...$$ 中的 LaTeX 公式
        "-t", "docx",                   # docx 写入器把公式输出为 Word 原生 OMML
        "--resource-path", src_dir,     # 图片相对路径（pic/ 等）
        "-o", docx_path,
    ]
    # 版式模板（正文首行缩进 2 字符、西文 Times New Roman 5号、代码 Courier New 小五）。
    # 模板不入库（*.docx 被 gitignore），缺失时先运行 make_reference_docx.py 生成。
    ref = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reference_book.docx")
    if os.path.isfile(ref):
        cmd += ["--reference-doc", ref]
    else:
        print("[提示] 未找到 reference_book.docx，输出将使用 pandoc 默认版式；"
              "可运行 python3 make_reference_docx.py 生成模板。", file=sys.stderr)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[失败] {md_path}\n{r.stderr}", file=sys.stderr)
        return False
    if r.stderr.strip():
        print(f"[pandoc 警告] {r.stderr.strip()}", file=sys.stderr)

    # ---- 公式转换完整性校验 ----
    md_text = open(md_path, encoding="utf-8").read()
    n_disp, n_inline = count_source_math(md_text)
    d_disp, d_total = count_docx_math(docx_path)
    ok = (d_disp >= n_disp) and (d_total >= n_disp + n_inline)
    size_kb = os.path.getsize(docx_path) // 1024
    print(f"[完成] {md_path} -> {docx_path}（{size_kb} KB）")
    print(f"       公式校验：源 行间 {n_disp} / 行内 {n_inline}；"
          f"docx OMML 行间 {d_disp} / 总计 {d_total} " + ("✓" if ok else "！数目不符"))
    if not ok:
        print("       警告：docx 中的 Word 公式数少于源文件公式数，"
              "可能有公式被当作普通文本，请检查上方 pandoc 警告。", file=sys.stderr)
    return ok


def main() -> None:
    pandoc = find_pandoc()
    args = sys.argv[1:]
    out_path = None
    if "-o" in args:                    # md2docx.py 文件.md -o 输出.docx
        i = args.index("-o")
        out_path = args[i + 1]
        args = args[:i] + args[i + 2:]
    files = args or ["chapter2_new.md", "chapter3_new.md"]
    if out_path and len(files) != 1:
        sys.exit("错误：-o 仅支持单个输入文件。")
    all_ok = True
    for f in files:
        if not os.path.isfile(f):
            print(f"[跳过] 文件不存在：{f}", file=sys.stderr)
            all_ok = False
            continue
        all_ok = convert(pandoc, f, out_path) and all_ok
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
