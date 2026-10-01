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
  * 行间公式自动按章编号：每个 $$...$$ 公式尾部追加 (章.序号)（如 (2.1)、
    (2.2)……），章号取自文首"# 第N章"标题（缺失时取文件名中的 chapterN）。
    编号在转换前的临时副本上追加，Markdown 源文件不被改动。
  * 转换后自动校验：统计源文件中的公式数（行间 $$ 块 + 行内 $ 对），
    与 docx 内部 word/document.xml 的 <m:oMath> 公式节点数比对，
    数目不符时给出警告，防止公式被悄悄转成纯文本。
  * 图片按相对路径（如 pic/2-1.png）嵌入 docx；Markdown 脚注转为 Word 页脚注。
  * 版式模板 reference_book.docx 与《chapter2_new_v3_公式修订稿.docx》对齐
    （正文宋体/Cambria 12pt、标题黑体/Calibri、代码 Consolas），由
    make_reference_docx.py 从 template/ 下的样式资产生成。

依赖：pandoc ≥ 2.19（脚本按 PANDOC 环境变量 → PATH → ~/.local/bin/pandoc 顺序查找）。
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
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


def detect_chapter(md_text: str, md_path: str) -> int | None:
    """章号：优先文首一级标题"# 第N章"，其次文件名中的 chapterN。"""
    m = re.search(r"^#\s*第\s*(\d+)\s*章", md_text, flags=re.M)
    if m:
        return int(m.group(1))
    m = re.search(r"chapter(\d+)", os.path.basename(md_path))
    return int(m.group(1)) if m else None


def number_equations(md_text: str, chapter: int) -> tuple[str, int]:
    """给所有行间公式（$$ 块）尾部追加编号 (章.序号)，返回 (新文本, 公式数)。

    逐行扫描：跳过 ``` 代码围栏；行间公式按独立的 "$$" 行界定（本书稿
    的统一写法），单行 "$$...$$" 也支持。编号追加在公式末尾内容行之后，
    以 \\qquad 与公式本体隔开，随公式一并转为 OMML。
    """
    lines = md_text.split("\n")
    in_code = False
    in_math = False
    last_content = None      # 当前公式块内最后一个非空行的下标
    n = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if not in_math:
            if s.startswith("```"):
                in_code = not in_code
                continue
            if in_code or not s.startswith("$$"):
                continue
            if s == "$$":                   # 纯定界行开块
                in_math, last_content = True, None
            elif s.endswith("$$") and len(s) > 4:   # 单行 $$...$$
                n += 1
                lines[i] = line[:line.rfind("$$")] + f" \\qquad ({chapter}.{n})$$"
            else:                           # $$内容 开块（跨行）
                in_math, last_content = True, i
        else:
            if s == "$$":                   # 纯定界行闭块
                in_math = False
                if last_content is not None:
                    n += 1
                    lines[last_content] += f" \\qquad ({chapter}.{n})"
            elif s.endswith("$$"):          # 内容$$ 闭块
                in_math = False
                n += 1
                lines[i] = line[:line.rfind("$$")] + f" \\qquad ({chapter}.{n})$$"
            elif s:
                last_content = i
    return "\n".join(lines), n


_MATH_RPR = '<w:rPr><w:rFonts w:ascii="Cambria Math" w:hAnsi="Cambria Math"/></w:rPr>'
_CTRL_PR = f'<m:ctrlPr>{_MATH_RPR}</m:ctrlPr>'
# 公式结构属性块（分隔符/分式/根式/求和/上下标等），schema 规定 ctrlPr 为其末子元素
_MATH_PR_TAGS = ("dPr|fPr|radPr|naryPr|sSubPr|sSupPr|sSubSupPr|funcPr|limLowPr|"
                 "limUppPr|groupChrPr|barPr|accPr|borderBoxPr|boxPr|eqArrPr|mPr|phantPr")
# 需要中文字体渲染的字符：CJK、全角标点、弯引号、破折号、省略号等歧义字符
_EA_CHARS = re.compile(r'[\u2014\u2018-\u201d\u2026\u3000-\u303f\u3400-\u9fff\uf900-\ufaff\uff00-\uffef]')


def _patch_math(xml: str) -> str:
    """OMML 补丁：pandoc 输出缺少字体声明，Word 靠默认值渲染而 WPS 不能。

    对齐公式修订稿 docx 的写法：1）删除 oMathParaPr（用文档默认的
    centerGroup 对齐）；2）每个数学运行 m:r 补 Cambria Math 字体；
    3）每个结构属性块补 m:ctrlPr（控制字符——括号、分数线等的字体）。
    """
    xml = re.sub(r'<m:oMathParaPr>.*?</m:oMathParaPr>', '', xml, flags=re.S)
    xml = re.sub(r'(<m:r>(?:<m:rPr\s*/>|<m:rPr>.*?</m:rPr>)?)(<m:t[ >])',
                 r'\1' + _MATH_RPR + r'\2', xml, flags=re.S)
    xml = re.sub(rf'</m:({_MATH_PR_TAGS})>', _CTRL_PR + r'</m:\1>', xml)
    return xml


def _patch_ea_hints(xml: str) -> str:
    """给含中文/全角字符的文本运行补 w:hint="eastAsia"。

    弯引号、破折号等在东西文字体中都有的歧义字符，无 hint 时 Word/WPS
    会用西文字体（Cambria）渲染，与公式修订稿（中文运行全部带 hint、
    歧义字符走宋体）不一致。"""
    def fix_run(m: re.Match) -> str:
        run = m.group(0)
        texts = ''.join(re.findall(r'<w:t[^>]*>([^<]*)</w:t>', run))
        if not _EA_CHARS.search(texts):
            return run
        if '<w:rFonts' in run:
            return run.replace('<w:rFonts ', '<w:rFonts w:hint="eastAsia" ', 1) \
                if 'w:hint=' not in run else run
        if '<w:rPr>' in run:
            # rFonts 须紧跟 rStyle 之后（schema 顺序）
            rpr_m = re.search(r'<w:rPr>(<w:rStyle [^>]*/>)?', run)
            return (run[:rpr_m.end()] + '<w:rFonts w:hint="eastAsia"/>'
                    + run[rpr_m.end():])
        return run.replace('<w:r>', '<w:r><w:rPr><w:rFonts w:hint="eastAsia"/></w:rPr>', 1)
    return re.sub(r'<w:r>(?:(?!</w:r>).)*</w:r>', fix_run, xml, flags=re.S)


def patch_docx(docx_path: str) -> None:
    """转换后处理，保证 WPS 兼容并与公式修订稿版式完全一致：
      * document.xml / footnotes.xml：OMML 字体补丁 + 中文运行 eastAsia hint；
      * settings.xml：换用 template/settings_v3.xml（含 m:mathPr 数学属性、
        useFELayout 中文版式模式、脚注分隔线设置）；
      * fontTable.xml：换用 template/fontTable_v3.xml（注册宋体/黑体/
        Cambria Math 及其 WPS 替换字体映射）。
    """
    tpl_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template")
    replace = {}
    for name, tpl in (("word/settings.xml", "settings_v3.xml"),
                      ("word/fontTable.xml", "fontTable_v3.xml")):
        p = os.path.join(tpl_dir, tpl)
        if os.path.isfile(p):
            replace[name] = open(p, "rb").read()
        else:
            print(f"[提示] 缺少 {p}，跳过 {name} 替换。", file=sys.stderr)

    tmp_path = docx_path + ".tmp"
    with zipfile.ZipFile(docx_path) as zin, \
            zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.filename in replace:
                data = replace[item.filename]
            elif item.filename in ("word/document.xml", "word/footnotes.xml"):
                xml = zin.read(item.filename).decode("utf-8")
                data = _patch_ea_hints(_patch_math(xml)).encode("utf-8")
            else:
                data = zin.read(item.filename)
            zout.writestr(item, data)
    os.replace(tmp_path, docx_path)


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
    md_text = open(md_path, encoding="utf-8").read()

    # ---- 行间公式按章编号（在临时副本上追加，不改源文件）----
    chapter = detect_chapter(md_text, md_path)
    n_numbered = 0
    input_path = md_path
    tmp_md = None
    if chapter is not None:
        numbered_text, n_numbered = number_equations(md_text, chapter)
        tmp_md = tempfile.NamedTemporaryFile(
            "w", suffix=".md", encoding="utf-8", delete=False)
        tmp_md.write(numbered_text)
        tmp_md.close()
        input_path = tmp_md.name
    else:
        print(f"[提示] {md_path} 未识别出章号（无\"# 第N章\"标题且文件名无 chapterN），"
              "跳过公式编号。", file=sys.stderr)

    cmd = [
        pandoc, input_path,
        # gfm+tex_math_dollars：识别 $...$ / $$...$$ 中的 LaTeX 公式；
        # -autolink_bare_uris：关闭裸 URL/邮箱自动成链——中文紧邻 "pass@1" 这类
        # 文本会被误识别为邮箱生成悬空超链接；脚注里的 URL 以纯文本呈现即可。
        "-f", "gfm+tex_math_dollars-autolink_bare_uris",
        "-t", "docx",                   # docx 写入器把公式输出为 Word 原生 OMML
        "--resource-path", src_dir,     # 图片相对路径（pic/ 等）
        "-o", docx_path,
    ]
    # 版式模板（与公式修订稿对齐：正文宋体/Cambria 12pt、标题黑体、代码 Consolas）。
    # 模板不入库（*.docx 被 gitignore），缺失时先运行 make_reference_docx.py 生成。
    ref = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reference_book.docx")
    if os.path.isfile(ref):
        cmd += ["--reference-doc", ref]
    else:
        print("[提示] 未找到 reference_book.docx，输出将使用 pandoc 默认版式；"
              "可运行 python3 make_reference_docx.py 生成模板。", file=sys.stderr)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        if tmp_md is not None:
            os.unlink(tmp_md.name)
    if r.returncode != 0:
        print(f"[失败] {md_path}\n{r.stderr}", file=sys.stderr)
        return False
    if r.stderr.strip():
        print(f"[pandoc 警告] {r.stderr.strip()}", file=sys.stderr)

    # ---- 转换后处理：WPS 兼容与版式对齐（详见 patch_docx 注释）----
    patch_docx(docx_path)

    # ---- 公式转换完整性校验（以源文件为准，编号追加不改变公式数）----
    n_disp, n_inline = count_source_math(md_text)
    d_disp, d_total = count_docx_math(docx_path)
    ok = (d_disp >= n_disp) and (d_total >= n_disp + n_inline)
    if chapter is not None and n_numbered != n_disp:
        print(f"       警告：编号公式数 {n_numbered} 与行间公式数 {n_disp} 不符，"
              "请检查公式定界写法。", file=sys.stderr)
        ok = False
    size_kb = os.path.getsize(docx_path) // 1024
    print(f"[完成] {md_path} -> {docx_path}（{size_kb} KB）")
    numbering = (f"；编号 ({chapter}.1)～({chapter}.{n_numbered})"
                 if chapter is not None and n_numbered else "")
    print(f"       公式校验：源 行间 {n_disp} / 行内 {n_inline}；"
          f"docx OMML 行间 {d_disp} / 总计 {d_total} "
          + ("✓" if ok else "！数目不符") + numbering)
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
