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


# ── stamp/read metadata ───────────────────────────────────
from git_review import stamp_docx_metadata, read_docx_metadata


def _make_bare_docx(path):
    """用 python-docx 造一个空白 docx 文件。"""
    from docx import Document
    Document().save(str(path))


def test_stamp_and_read_roundtrip(tmp_path):
    d = tmp_path / 'x.docx'
    _make_bare_docx(d)
    sha_full = 'a' * 40
    base_full = 'b' * 40
    stamp_docx_metadata(
        docx_path=str(d),
        source_git_commit=sha_full,
        source_base_commit=base_full,
        source_path='chapter3_new.md',
        exported_at='2026-04-23T16:37:00Z',
    )
    meta = read_docx_metadata(str(d))
    assert meta['SourceGitCommit'] == sha_full
    assert meta['SourceBaseCommit'] == base_full
    assert meta['SourcePath'] == 'chapter3_new.md'
    assert meta['ReviewExportedAt'] == '2026-04-23T16:37:00Z'


def test_read_docx_metadata_no_custom_xml_returns_empty(tmp_path):
    d = tmp_path / 'empty.docx'
    _make_bare_docx(d)
    meta = read_docx_metadata(str(d))
    assert meta == {}


def test_stamp_is_idempotent(tmp_path):
    """重复 stamp 应覆盖旧值而不是追加重复项。"""
    d = tmp_path / 'x.docx'
    _make_bare_docx(d)
    stamp_docx_metadata(str(d), 'a' * 40, 'b' * 40, 'x.md', 't1')
    stamp_docx_metadata(str(d), 'c' * 40, 'd' * 40, 'y.md', 't2')
    meta = read_docx_metadata(str(d))
    assert meta['SourceGitCommit'] == 'c' * 40
    assert meta['SourcePath'] == 'y.md'
    assert meta['ReviewExportedAt'] == 't2'


# ── resolve_baseline ──────────────────────────────────────
from git_review import resolve_baseline


def test_resolve_baseline_from_metadata(tmp_path, tmp_git_repo):
    sha = _commit(tmp_git_repo, 'chapter.md', 'v1\n', 'c1')
    docx = tmp_path / 'anything.docx'
    _make_bare_docx(docx)
    stamp_docx_metadata(str(docx), sha, sha, 'chapter.md', '2026-04-23T00:00:00Z')

    base, path, kind = resolve_baseline(str(docx), repo=str(tmp_git_repo))
    assert base == sha
    assert path == 'chapter.md'
    assert kind == 'metadata'


def test_resolve_baseline_from_filename(tmp_path, tmp_git_repo):
    sha = _commit(tmp_git_repo, 'chapter.md', 'v1\n', 'c1')
    short = sha[:7]
    docx = tmp_path / f'chapter_{short}.docx'
    _make_bare_docx(docx)

    base, path, kind = resolve_baseline(
        str(docx), repo=str(tmp_git_repo), cli_path='chapter.md')
    assert base == sha
    assert path == 'chapter.md'
    assert kind == 'filename'


def test_resolve_baseline_from_sidecar(tmp_path, tmp_git_repo):
    sha = _commit(tmp_git_repo, 'chapter.md', 'v1\n', 'c1')
    docx = tmp_path / 'foo.docx'
    _make_bare_docx(docx)
    (tmp_path / 'foo.docx.base').write_text(sha + '\n', encoding='utf-8')

    base, path, kind = resolve_baseline(
        str(docx), repo=str(tmp_git_repo), cli_path='chapter.md')
    assert base == sha
    assert kind == 'sidecar'


def test_resolve_baseline_from_cli(tmp_path, tmp_git_repo):
    sha = _commit(tmp_git_repo, 'chapter.md', 'v1\n', 'c1')
    docx = tmp_path / 'mystery.docx'
    _make_bare_docx(docx)

    base, path, kind = resolve_baseline(
        str(docx), repo=str(tmp_git_repo),
        cli_base=sha, cli_path='chapter.md')
    assert base == sha
    assert path == 'chapter.md'
    assert kind == 'cli'


def test_resolve_baseline_all_fail(tmp_path, tmp_git_repo):
    _commit(tmp_git_repo, 'chapter.md', 'v1\n', 'c1')
    docx = tmp_path / 'mystery.docx'
    _make_bare_docx(docx)
    with pytest.raises(GitReviewError, match='baseline'):
        resolve_baseline(str(docx), repo=str(tmp_git_repo))


def test_resolve_baseline_metadata_sha_not_in_repo(tmp_path, tmp_git_repo):
    _commit(tmp_git_repo, 'chapter.md', 'v1\n', 'c1')
    docx = tmp_path / 'x.docx'
    _make_bare_docx(docx)
    stamp_docx_metadata(str(docx), 'd' * 40, 'e' * 40, 'chapter.md', 't')
    # metadata 指向仓库里不存在的 sha，应继续回退
    with pytest.raises(GitReviewError):
        resolve_baseline(str(docx), repo=str(tmp_git_repo))


def test_resolve_baseline_metadata_path_missing(tmp_path, tmp_git_repo):
    sha = _commit(tmp_git_repo, 'chapter.md', 'v1\n', 'c1')
    docx = tmp_path / 'x.docx'
    _make_bare_docx(docx)
    stamp_docx_metadata(str(docx), sha, sha, 'no_such_file.md', 't')
    with pytest.raises(GitReviewError, match='SourcePath'):
        resolve_baseline(str(docx), repo=str(tmp_git_repo))


# ── detect_reviewer ───────────────────────────────────────
from git_review import detect_reviewer


def test_detect_reviewer_cli_wins_over_docx(tmp_path):
    d = tmp_path / 'x.docx'
    _make_bare_docx(d)
    name, slug = detect_reviewer(cli_reviewer='张三',
                                 reviewed_docx_path=str(d))
    assert name == '张三'
    assert slug == 'zhangsan'


def test_detect_reviewer_english_name():
    name, slug = detect_reviewer(cli_reviewer='John Doe',
                                 reviewed_docx_path='')
    assert name == 'John Doe'
    assert slug == 'john-doe'


def test_detect_reviewer_mixed_and_trimmed():
    name, slug = detect_reviewer(cli_reviewer='  张三_Reviewer  ',
                                 reviewed_docx_path='')
    assert name == '张三_Reviewer'
    assert slug == 'zhangsanreviewer'


def test_detect_reviewer_fallback_unknown(tmp_path):
    d = tmp_path / 'x.docx'
    _make_bare_docx(d)
    name, slug = detect_reviewer(cli_reviewer=None,
                                 reviewed_docx_path=str(d))
    assert name == 'unknown'
    assert slug == 'unknown'


# ── commit_to_review_branch ───────────────────────────────
from git_review import commit_to_review_branch, update_review_state


def _current_head(repo):
    return subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()


def _current_branch(repo):
    return subprocess.check_output(
        ['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=repo, text=True).strip()


def test_commit_to_review_branch_creates_branch_without_switching_head(tmp_git_repo):
    base_sha = _commit(tmp_git_repo, 'chapter.md', 'old\n', 'init')
    main_head_before = _current_head(tmp_git_repo)
    main_branch_before = _current_branch(tmp_git_repo)

    branch_ref, new_sha = commit_to_review_branch(
        repo=str(tmp_git_repo),
        reviewer_slug='zhangsan',
        reviewer_name='张三',
        base_sha=base_sha,
        md_path='chapter.md',
        new_md_bytes=b'new\n',
        commit_message='review: 1 处文本修改\n',
        docx_filename='reviewed.docx',
        date_str='20260423',
    )

    # HEAD 没被切走
    assert _current_head(tmp_git_repo) == main_head_before
    assert _current_branch(tmp_git_repo) == main_branch_before

    # 分支存在
    assert branch_ref == 'refs/heads/review/zhangsan-20260423'
    out = subprocess.check_output(
        ['git', 'rev-parse', branch_ref], cwd=tmp_git_repo, text=True).strip()
    assert out == new_sha

    # commit 内容正确
    content = subprocess.check_output(
        ['git', 'show', f'{new_sha}:chapter.md'],
        cwd=tmp_git_repo, text=True)
    assert content == 'new\n'

    # author / committer 正确
    info = subprocess.check_output(
        ['git', 'log', '-1', '--pretty=%an|%ae|%cn|%ce', new_sha],
        cwd=tmp_git_repo, text=True).strip()
    an, ae, cn, ce = info.split('|')
    assert an == '张三'
    assert ae == 'zhangsan@review.local'
    assert cn == 'md-docx-bridge'
    assert ce == 'bridge@review.local'


def test_commit_to_review_branch_suffix_on_collision(tmp_git_repo):
    base_sha = _commit(tmp_git_repo, 'chapter.md', 'old\n', 'init')

    r1, s1 = commit_to_review_branch(
        repo=str(tmp_git_repo), reviewer_slug='zhangsan', reviewer_name='张三',
        base_sha=base_sha, md_path='chapter.md',
        new_md_bytes=b'v1\n', commit_message='m1',
        docx_filename='a.docx', date_str='20260423')

    r2, s2 = commit_to_review_branch(
        repo=str(tmp_git_repo), reviewer_slug='zhangsan', reviewer_name='张三',
        base_sha=base_sha, md_path='chapter.md',
        new_md_bytes=b'v2\n', commit_message='m2',
        docx_filename='b.docx', date_str='20260423')

    assert r1 == 'refs/heads/review/zhangsan-20260423'
    assert r2 == 'refs/heads/review/zhangsan-20260423-2'
    assert s1 != s2


def test_update_review_state_appends_and_sets_last(tmp_path):
    state = tmp_path / '.review_state.json'
    state.write_text(json.dumps({
        'last_exported_sha': None,
        'last_exported_at': None,
        'exports': [],
    }), encoding='utf-8')

    update_review_state(str(state), sha='a' * 40,
                        exported_at='2026-04-23T00:00:00Z',
                        file_name='x_aaaaaaa.docx',
                        base_sha='b' * 40)
    data = json.loads(state.read_text())
    assert data['last_exported_sha'] == 'a' * 40
    assert data['last_exported_at'] == '2026-04-23T00:00:00Z'
    assert len(data['exports']) == 1
    assert data['exports'][0]['sha'] == 'a' * 40
    assert data['exports'][0]['file'] == 'x_aaaaaaa.docx'
    assert data['exports'][0]['base'] == 'b' * 40
