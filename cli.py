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


def cmd_export_review(args):
    """生成带 Track Changes 的送审 docx。"""
    import datetime
    from md_core import parse_md_blocks
    from md_diff_docx import DiffDocxRenderer
    from git_review import (
        resolve_range, read_at, stamp_docx_metadata, update_review_state,
        GitReviewError,
    )

    try:
        base_sha, head_sha = resolve_range(
            args.range_arg,
            repo='.',
            state_path='.review_state.json',
        )
    except GitReviewError as e:
        print(f'错误: {e}', file=sys.stderr)
        sys.exit(1)

    try:
        old_text = read_at(base_sha, args.path, repo='.')
        new_text = read_at(head_sha, args.path, repo='.')
    except GitReviewError as e:
        print(f'错误: {e}', file=sys.stderr)
        sys.exit(1)

    old_blocks = parse_md_blocks(old_text)
    new_blocks = parse_md_blocks(new_text)

    basename = os.path.splitext(os.path.basename(args.path))[0]
    out_name = args.output or f'{basename}_{head_sha[:7]}.docx'

    renderer = DiffDocxRenderer(use_comments=args.comments,
                                author=args.author or 'AutoDiff')
    renderer.render_diff(old_blocks, new_blocks)
    renderer.save(out_name)

    exported_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        '%Y-%m-%dT%H:%M:%SZ')
    stamp_docx_metadata(
        docx_path=out_name,
        source_git_commit=head_sha,
        source_base_commit=base_sha,
        source_path=args.path,
        exported_at=exported_at,
    )
    update_review_state(
        '.review_state.json',
        sha=head_sha, exported_at=exported_at,
        file_name=os.path.basename(out_name),
        base_sha=base_sha,
    )
    print(f'✅ 送审文档: {out_name}')
    print(f'   基线: {base_sha[:7]}  送审版本: {head_sha[:7]}')


def cmd_import_review(args):
    """回灌：审校 docx → review 分支 commit。"""
    import datetime
    import os as _os
    import subprocess as _sp
    from docx_reader import read_docx, DocxReaderError
    from docx_to_md import (
        make_edits_with_comments, apply_edits_to_md, render_commit_message,
    )
    from git_review import (
        resolve_baseline, read_at, detect_reviewer, commit_to_review_branch,
        GitReviewError,
    )

    # 0. 工作区干净检查 — 只拒绝 tracked 文件的未提交改动；untracked 文件
    #    （通常是审校 docx 本身）允许存在。
    if not args.allow_dirty:
        unstaged = _sp.run(['git', 'diff', '--quiet'],
                           capture_output=True, check=False).returncode
        staged = _sp.run(['git', 'diff', '--cached', '--quiet'],
                         capture_output=True, check=False).returncode
        if unstaged or staged:
            print('错误: 工作区有未提交改动（tracked 文件）。请先 git stash / '
                  'git commit 再 import-review，或加 --allow-dirty 强行继续。',
                  file=sys.stderr)
            diff_out = _sp.run(['git', 'status', '--porcelain', '--untracked-files=no'],
                               capture_output=True, text=True, check=False).stdout
            print(diff_out, file=sys.stderr)
            sys.exit(1)

    # 1. 基线
    try:
        base_sha, source_path, baseline_source = resolve_baseline(
            args.docx, repo='.', cli_base=args.base, cli_path=args.path,
        )
    except GitReviewError as e:
        print(f'错误: {e}', file=sys.stderr)
        sys.exit(1)

    # 2. baseline md
    try:
        baseline_md = read_at(base_sha, source_path, repo='.')
    except GitReviewError as e:
        print(f'错误: {e}', file=sys.stderr)
        sys.exit(1)

    # 3. reviewed docx
    try:
        reviewed_blocks = read_docx(args.docx)
    except DocxReaderError as e:
        print(f'错误: {e}', file=sys.stderr)
        sys.exit(2)

    # 4. media bundle — 从 docx 再读一次抽取 sha -> bytes
    import zipfile as _zf
    import hashlib as _hash
    media_by_sha: dict = {}
    try:
        with _zf.ZipFile(args.docx, 'r') as z:
            for n in z.namelist():
                if n.startswith('word/media/'):
                    data = z.read(n)
                    media_by_sha[_hash.sha256(data).hexdigest()] = data
    except _zf.BadZipFile:
        pass

    # 5. reviewer
    reviewer, slug = detect_reviewer(args.reviewer, args.docx)

    # 6. classifier
    classify_fn = _build_classify_fn()

    # 7. 计算 edits
    edits = make_edits_with_comments(
        baseline_md, reviewed_blocks,
        media=media_by_sha, classify_fn=classify_fn,
    )

    if not edits:
        print('未检测到实质改动；不创建 commit。')
        sys.exit(0)

    # 8. apply + message
    new_md, warnings = apply_edits_to_md(baseline_md, edits)
    msg = render_commit_message(
        edits=edits, warnings=warnings,
        reviewer=reviewer,
        docx_filename=_os.path.basename(args.docx),
        base_sha=base_sha,
        baseline_source=baseline_source,
    )

    # 9. commit
    date_str = datetime.datetime.now().strftime('%Y%m%d')
    branch_ref, new_sha = commit_to_review_branch(
        repo='.',
        reviewer_slug=slug,
        reviewer_name=reviewer,
        base_sha=base_sha,
        md_path=source_path,
        new_md_bytes=new_md.encode('utf-8'),
        commit_message=msg,
        docx_filename=_os.path.basename(args.docx),
        date_str=date_str,
    )
    print(f'✅ 审校 commit 已写入 {branch_ref}  ({new_sha[:7]})')
    print(f'   review: {len(edits)} 条变动，warnings={len(warnings)}')
    branch_name = branch_ref.replace('refs/heads/', '')
    print(f'   手动合并： git merge --no-ff {branch_name}')


def _build_classify_fn():
    """构造 classify_fn(block_text, anchor_text, comment_body, md_context) -> dict。
    有 ANTHROPIC_API_KEY 则用真实 client；否则 client=None 全部降级为 opinion。"""
    from comment_classifier import classify
    client = None
    if os.environ.get('ANTHROPIC_API_KEY'):
        try:
            import anthropic
            client = anthropic.Anthropic()
        except Exception as e:
            print(f'⚠ 无法创建 Anthropic 客户端: {e}; 批注全部走 opinion 降级',
                  file=sys.stderr)
            client = None

    def _fn(**kwargs):
        return classify(client=client, **kwargs)
    return _fn


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

    # ── export-review 子命令 ────────────────────────────────
    p_exp = subparsers.add_parser(
        'export-review',
        help='以 git commit 差异生成送审 docx（带 Track Changes）'
    )
    p_exp.add_argument('range_arg', metavar='RANGE',
                       help='<commit> 或 <base>..<head> 或 --since-last-review')
    p_exp.add_argument('--path', required=True,
                       help='仓库内相对路径，如 chapter3_new.md')
    p_exp.add_argument('-o', '--output',
                       help='输出 docx 路径（默认 <basename>_<head_sha7>.docx）')
    p_exp.add_argument('--comments', action='store_true',
                       help='使用批注模式（默认 Track Changes）')
    p_exp.add_argument('--author', default='AutoDiff',
                       help='修订作者名')

    # ── import-review 子命令 ────────────────────────────────
    p_imp = subparsers.add_parser(
        'import-review',
        help='把审校 docx 回灌到 review/ 分支上的 commit'
    )
    p_imp.add_argument('docx', help='审校后的 docx 路径')
    p_imp.add_argument('--reviewer', help='审校者显示名（中英文均可）')
    p_imp.add_argument('--base', help='基线 commit sha（四级回退兜底）')
    p_imp.add_argument('--path', help='仓库内 md 相对路径（与 --base 配套）')
    p_imp.add_argument('--allow-dirty', action='store_true',
                       help='跳过工作区干净检查（默认脏则拒绝）')

    args = parser.parse_args()

    if args.command == 'convert':
        cmd_convert(args)
    elif args.command == 'diff':
        cmd_diff(args)
    elif args.command == 'export-review':
        cmd_export_review(args)
    elif args.command == 'import-review':
        cmd_import_review(args)


if __name__ == '__main__':
    main()
