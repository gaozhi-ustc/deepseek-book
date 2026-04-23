"""git_review.py — md↔docx 审校桥的 git 封装层。

所有函数都走 subprocess 调真实 git 命令，不依赖 GitPython。
保持无状态：任何需要 repo 定位的函数都接受 `repo=` 参数。
"""
import json
import os
import subprocess
from typing import Optional, Tuple


class GitReviewError(RuntimeError):
    """git_review 层的错误。"""


# ──────────────────────────────────────────────────────────
# subprocess 辅助
# ──────────────────────────────────────────────────────────

def _git(args, repo: str, *, input_bytes: Optional[bytes] = None,
         env: Optional[dict] = None, capture: bool = True) -> bytes:
    """运行 git 命令，抛 GitReviewError 时带 stderr。"""
    try:
        proc = subprocess.run(
            ['git'] + list(args),
            cwd=repo,
            input=input_bytes,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE,
            env={**os.environ, **(env or {})},
            check=True,
        )
        return proc.stdout
    except subprocess.CalledProcessError as e:
        raise GitReviewError(
            f'git {" ".join(args)} failed: {e.stderr.decode("utf-8", "replace").strip()}'
        ) from e


def _rev_parse(ref: str, repo: str) -> str:
    out = _git(['rev-parse', '--verify', f'{ref}^{{commit}}'], repo=repo)
    return out.decode('ascii').strip()


# ──────────────────────────────────────────────────────────
# read_at
# ──────────────────────────────────────────────────────────

def read_at(sha: str, path: str, repo: str = '.') -> str:
    """`git show <sha>:<path>` 的 UTF-8 文本形式。"""
    out = _git(['show', f'{sha}:{path}'], repo=repo)
    return out.decode('utf-8')


# ──────────────────────────────────────────────────────────
# resolve_range
# ──────────────────────────────────────────────────────────

def resolve_range(arg: str, repo: str = '.',
                  state_path: str = '.review_state.json') -> Tuple[str, str]:
    """解析 CLI 传入的 commit 范围参数，返回 (base_sha, head_sha) 全 40 位。

    支持：
      - `<commit>`             → (<commit>^, <commit>)
      - `<base>..<head>`       → (<base>, <head>)
      - `--since-last-review`  → (state.last_exported_sha, HEAD)
    """
    if arg == '--since-last-review':
        if not os.path.exists(state_path):
            raise GitReviewError(
                f'--since-last-review 需要 {state_path}，但文件不存在')
        with open(state_path, 'r', encoding='utf-8') as f:
            state = json.load(f)
        last = state.get('last_exported_sha')
        if not last:
            raise GitReviewError(
                '--since-last-review: .review_state.json 里没有 last_exported_sha，'
                '请先运行一次具体 commit 的 export-review')
        head = _rev_parse('HEAD', repo=repo)
        base = _rev_parse(last, repo=repo)
        return base, head

    if '..' in arg:
        base_ref, head_ref = arg.split('..', 1)
        if not base_ref or not head_ref:
            raise GitReviewError(f'无效的 range 语法: {arg!r}')
        return _rev_parse(base_ref, repo=repo), _rev_parse(head_ref, repo=repo)

    head = _rev_parse(arg, repo=repo)
    base = _rev_parse(f'{arg}^', repo=repo)
    return base, head
