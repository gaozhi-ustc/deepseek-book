"""git_review.py 的单元测试，全部走真实 git（tmp 仓库），不 mock。"""
import json
import subprocess
from pathlib import Path

import pytest

from git_review import (
    read_at, resolve_range,
    GitReviewError,
)


def _commit(repo: Path, file: str, content: str, msg: str) -> str:
    (repo / file).write_text(content, encoding='utf-8')
    subprocess.run(['git', 'add', file], cwd=repo, check=True)
    subprocess.run(['git', 'commit', '-q', '-m', msg], cwd=repo, check=True)
    return subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=repo, text=True
    ).strip()


# ── read_at ────────────────────────────────────────────────
def test_read_at_reads_historical_file(tmp_git_repo):
    sha1 = _commit(tmp_git_repo, 'chapter.md', 'v1\n', 'c1')
    sha2 = _commit(tmp_git_repo, 'chapter.md', 'v2\n', 'c2')

    assert read_at(sha1, 'chapter.md', repo=str(tmp_git_repo)) == 'v1\n'
    assert read_at(sha2, 'chapter.md', repo=str(tmp_git_repo)) == 'v2\n'


def test_read_at_missing_path_raises(tmp_git_repo):
    sha = _commit(tmp_git_repo, 'chapter.md', 'x\n', 'c')
    with pytest.raises(GitReviewError):
        read_at(sha, 'nope.md', repo=str(tmp_git_repo))


# ── resolve_range ─────────────────────────────────────────
def test_resolve_range_single_commit(tmp_git_repo):
    sha1 = _commit(tmp_git_repo, 'a.md', 'a\n', 'c1')
    sha2 = _commit(tmp_git_repo, 'a.md', 'b\n', 'c2')
    base, head = resolve_range(sha2, repo=str(tmp_git_repo))
    assert base == sha1
    assert head == sha2


def test_resolve_range_dotdot(tmp_git_repo):
    sha1 = _commit(tmp_git_repo, 'a.md', 'a\n', 'c1')
    sha2 = _commit(tmp_git_repo, 'a.md', 'b\n', 'c2')
    sha3 = _commit(tmp_git_repo, 'a.md', 'c\n', 'c3')
    base, head = resolve_range(f'{sha1}..{sha3}', repo=str(tmp_git_repo))
    assert base == sha1
    assert head == sha3


def test_resolve_range_since_last_review(tmp_git_repo):
    sha1 = _commit(tmp_git_repo, 'a.md', 'a\n', 'c1')
    sha2 = _commit(tmp_git_repo, 'a.md', 'b\n', 'c2')
    sha3 = _commit(tmp_git_repo, 'a.md', 'c\n', 'c3')

    state = tmp_git_repo / '.review_state.json'
    state.write_text(json.dumps({
        'last_exported_sha': sha1,
        'last_exported_at': '2026-01-01T00:00:00Z',
        'exports': [],
    }), encoding='utf-8')

    base, head = resolve_range('--since-last-review',
                               repo=str(tmp_git_repo),
                               state_path=str(state))
    assert base == sha1
    assert head == sha3  # HEAD


def test_resolve_range_since_last_review_empty_state(tmp_git_repo):
    _commit(tmp_git_repo, 'a.md', 'a\n', 'c1')
    state = tmp_git_repo / '.review_state.json'
    state.write_text(json.dumps({
        'last_exported_sha': None,
        'last_exported_at': None,
        'exports': [],
    }), encoding='utf-8')
    with pytest.raises(GitReviewError, match='没有 last_exported_sha'):
        resolve_range('--since-last-review',
                      repo=str(tmp_git_repo), state_path=str(state))


def test_resolve_range_bad_commit(tmp_git_repo):
    _commit(tmp_git_repo, 'a.md', 'a\n', 'c1')
    with pytest.raises(GitReviewError):
        resolve_range('deadbeef', repo=str(tmp_git_repo))
