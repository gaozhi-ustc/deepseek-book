#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cli.py — Markdown → DOCX 工具集统一入口

子命令：
  convert   将 Markdown 文件转换为符合13条规范的 DOCX
  diff      将两个 Markdown 文件的差异转为 Word 修订文档

用法：
  python cli.py convert input.md [-o output.docx] [--no-format]
  python cli.py diff old.md new.md [-o diff.docx] [--comments] [--author "Name"]
  python cli.py diff --from-diff [patch.diff] [-o diff.docx]
  git diff HEAD~1 HEAD file.md | python cli.py diff --from-diff -o diff.docx
"""

import sys
import os
import argparse


def cmd_convert(args):
    if not os.path.exists(args.input):
        print(f"错误: 文件不存在 {args.input}")
        sys.exit(1)

    if args.no_format:
        from md_core import convert_md_to_docx
        convert_md_to_docx(args.input, args.output, xsl_path=args.xsl)
    else:
        from md_formatter import convert_formatted
        convert_formatted(args.input, args.output, xsl_path=args.xsl)


def cmd_diff(args):
    from md_diff_docx import diff_md_files, diff_from_unified, REVISION_AUTHOR

    author = args.author or REVISION_AUTHOR
    use_comments = args.comments

    if not args.output:
        print("错误: 必须指定 -o 输出文件")
        sys.exit(1)

    if args.from_diff is not None:
        # 从 unified diff 读取
        if args.from_diff == '-' or args.from_diff == '':
            if sys.stdin.isatty():
                print("错误: --from-diff 需要指定文件路径，或通过管道传入 diff 内容")
                sys.exit(1)
            diff_text = sys.stdin.read()
        else:
            if not os.path.exists(args.from_diff):
                print(f"错误: diff 文件不存在 {args.from_diff}")
                sys.exit(1)
            with open(args.from_diff, 'r', encoding='utf-8') as f:
                diff_text = f.read()
        diff_from_unified(diff_text, args.output, use_comments, author)

    elif args.files and len(args.files) == 2:
        old_file, new_file = args.files
        for f in [old_file, new_file]:
            if not os.path.exists(f):
                print(f"错误: 文件不存在 {f}")
                sys.exit(1)
        diff_md_files(old_file, new_file, args.output, use_comments, author)

    elif not sys.stdin.isatty():
        # 从 stdin 读取 diff
        diff_text = sys.stdin.read()
        diff_from_unified(diff_text, args.output, use_comments, author)

    else:
        print("错误: 请指定两个 Markdown 文件，或通过 --from-diff 提供 diff 内容")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog='cli.py',
        description='Markdown → DOCX 工具集',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 转换（带规范格式）
  python cli.py convert chapter3.md -o chapter3.docx

  # 转换（基础模式，不应用规范层）
  python cli.py convert chapter3.md --no-format -o chapter3_raw.docx

  # Diff：两文件对比
  python cli.py diff old_chapter3.md new_chapter3.md -o diff.docx

  # Diff：从 git diff 输出
  git diff HEAD~1 HEAD chapter3.md | python cli.py diff --from-diff -o diff.docx

  # Diff：批注模式
  python cli.py diff old.md new.md --comments -o diff.docx
        """
    )
    subparsers = parser.add_subparsers(dest='command', required=True)

    # ── convert 子命令 ─────────────────────────────────────
    p_convert = subparsers.add_parser(
        'convert',
        help='将 Markdown 转换为 DOCX（符合13条写作规范）'
    )
    p_convert.add_argument('input', help='输入 Markdown 文件路径')
    p_convert.add_argument('-o', '--output', help='输出 DOCX 文件路径（默认与输入同名）')
    p_convert.add_argument('--no-format', action='store_true',
                           help='跳过规范层，仅做基础格式转换')
    p_convert.add_argument('--xsl', help='自定义 MML2OMML.XSL 路径')

    # ── diff 子命令 ────────────────────────────────────────
    p_diff = subparsers.add_parser(
        'diff',
        help='将两个 Markdown 版本的差异转为 Word 修订文档'
    )
    p_diff.add_argument('files', nargs='*', metavar='FILE',
                        help='old.md new.md（两文件对比模式）')
    p_diff.add_argument('--from-diff', metavar='PATCH',
                        help='从 unified diff 文件读取（- 或省略表示从 stdin 读取）')
    p_diff.add_argument('-o', '--output', required=True, help='输出 DOCX 文件路径')
    p_diff.add_argument('--comments', action='store_true',
                        help='使用批注模式（默认为 Track Changes 修订标记）')
    p_diff.add_argument('--author', default='AutoDiff',
                        help='修订作者名（默认: AutoDiff）')

    args = parser.parse_args()

    if args.command == 'convert':
        cmd_convert(args)
    elif args.command == 'diff':
        cmd_diff(args)


if __name__ == '__main__':
    main()
