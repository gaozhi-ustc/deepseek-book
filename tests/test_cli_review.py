"""cli.py 的 export-review / import-review 端到端测试（用 tmp_git_repo）。"""
import json
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run_cli(*args, cwd):
    """以当前 python3.14 运行 cli.py，cwd 内执行。"""
    cmd = [sys.executable, str(PROJECT_ROOT / 'cli.py'), *args]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def _commit(repo: Path, file: str, content: str, msg: str) -> str:
    (repo / file).write_text(content, encoding='utf-8')
    subprocess.run(['git', 'add', file], cwd=repo, check=True)
    subprocess.run(['git', 'commit', '-q', '-m', msg], cwd=repo, check=True)
    return subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()


MIN_MD = '# 标题\n\n第一段。\n'
MIN_MD_V2 = '# 标题\n\n第一段（已改）。\n'


def test_export_review_commit_creates_docx_with_metadata(tmp_git_repo):
    # 初始状态
    (tmp_git_repo / '.review_state.json').write_text(
        json.dumps({'last_exported_sha': None, 'last_exported_at': None, 'exports': []}),
        encoding='utf-8')
    _commit(tmp_git_repo, 'chapter.md', MIN_MD, 'v1')
    sha2 = _commit(tmp_git_repo, 'chapter.md', MIN_MD_V2, 'v2')

    r = _run_cli('export-review', sha2, '--path', 'chapter.md',
                 cwd=tmp_git_repo)
    assert r.returncode == 0, r.stderr

    # 输出文件存在
    short = sha2[:7]
    out = tmp_git_repo / f'chapter_{short}.docx'
    assert out.exists()

    # metadata 正确
    from git_review import read_docx_metadata
    meta = read_docx_metadata(str(out))
    assert meta['SourceGitCommit'] == sha2
    assert meta['SourcePath'] == 'chapter.md'

    # .review_state.json 更新
    state = json.loads((tmp_git_repo / '.review_state.json').read_text())
    assert state['last_exported_sha'] == sha2
    assert len(state['exports']) == 1


def test_export_review_dotdot_range(tmp_git_repo):
    (tmp_git_repo / '.review_state.json').write_text(
        json.dumps({'last_exported_sha': None, 'last_exported_at': None, 'exports': []}),
        encoding='utf-8')
    sha1 = _commit(tmp_git_repo, 'chapter.md', MIN_MD, 'v1')
    _commit(tmp_git_repo, 'chapter.md', MIN_MD_V2, 'v2')
    sha3 = _commit(tmp_git_repo, 'chapter.md',
                   '# 标题\n\n第一段（改两次）。\n', 'v3')
    r = _run_cli('export-review', f'{sha1}..{sha3}', '--path', 'chapter.md',
                 cwd=tmp_git_repo)
    assert r.returncode == 0, r.stderr
    assert (tmp_git_repo / f'chapter_{sha3[:7]}.docx').exists()


def test_import_review_no_changes_exits_without_commit(tmp_git_repo):
    """export-review 产出的未修改 docx 反向 import 应该 exit 0 但不创建 branch
    （reviewer 还没改动任何东西）。"""
    (tmp_git_repo / '.review_state.json').write_text(
        json.dumps({'last_exported_sha': None, 'last_exported_at': None, 'exports': []}),
        encoding='utf-8')
    _commit(tmp_git_repo, 'chapter.md', MIN_MD, 'v1')
    sha2 = _commit(tmp_git_repo, 'chapter.md', MIN_MD_V2, 'v2')

    r = _run_cli('export-review', sha2, '--path', 'chapter.md',
                 cwd=tmp_git_repo)
    assert r.returncode == 0, r.stderr
    docx = tmp_git_repo / f'chapter_{sha2[:7]}.docx'

    r = _run_cli('import-review', str(docx),
                 '--reviewer', '测试员', cwd=tmp_git_repo)
    assert r.returncode == 0
    assert '未检测到实质改动' in r.stdout
    branches = subprocess.check_output(
        ['git', 'branch', '-a'], cwd=tmp_git_repo, text=True)
    assert 'review/' not in branches


def test_import_review_with_actual_changes_creates_branch_without_touching_head(tmp_git_repo):
    """构造一份"审校者改过"的 docx（与基线真的不同），验证分支创建 & HEAD 不动。"""
    sys.path.insert(0, str(PROJECT_ROOT))
    from tests.fixtures.build_min_docx import write_docx, make_paragraph, make_heading
    from git_review import stamp_docx_metadata

    base_sha = _commit(tmp_git_repo, 'chapter.md', MIN_MD, 'v1')

    # 构造带真实改动的 docx：与 MIN_MD (# 标题 + 第一段。) 不同
    body = '\n'.join([
        make_heading(1, '标题'),
        make_paragraph('第一段已被审校者改过。'),
    ])
    docx = tmp_git_repo / 'reviewed.docx'
    write_docx(str(docx), body)
    # stamp 基线
    stamp_docx_metadata(str(docx), base_sha, base_sha, 'chapter.md',
                        '2026-04-24T00:00:00Z')

    head_before = subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=tmp_git_repo, text=True).strip()
    main_branch_before = subprocess.check_output(
        ['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=tmp_git_repo, text=True).strip()

    r = _run_cli('import-review', str(docx),
                 '--reviewer', '测试员', cwd=tmp_git_repo)
    assert r.returncode == 0, r.stderr

    # HEAD 未变
    head_after = subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=tmp_git_repo, text=True).strip()
    assert head_after == head_before
    main_branch_after = subprocess.check_output(
        ['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=tmp_git_repo, text=True).strip()
    assert main_branch_after == main_branch_before

    # review 分支存在
    branches = subprocess.check_output(
        ['git', 'branch', '-a'], cwd=tmp_git_repo, text=True)
    assert 'review/ceshiyuan-' in branches

    # 分支上的 commit author 是审校者
    branch = [l.strip().lstrip('* ').strip() for l in branches.splitlines()
              if 'review/ceshiyuan' in l][0]
    info = subprocess.check_output(
        ['git', 'log', '-1', '--pretty=%an|%cn', branch],
        cwd=tmp_git_repo, text=True).strip()
    an, cn = info.split('|')
    assert an == '测试员'
    assert cn == 'md-docx-bridge'


def test_import_review_missing_baseline_fails(tmp_git_repo):
    """docx 无 metadata、无匹配文件名、无 sidecar、无 CLI base → exit 1。"""
    _commit(tmp_git_repo, 'chapter.md', MIN_MD, 'v1')
    docx = tmp_git_repo / 'mystery.docx'
    # 最小 docx（python-docx）
    from docx import Document
    Document().save(str(docx))

    r = _run_cli('import-review', str(docx),
                 '--reviewer', '测试员',
                 cwd=tmp_git_repo)
    assert r.returncode != 0
    assert 'baseline' in (r.stderr + r.stdout).lower()


def test_import_review_rejects_dirty_worktree(tmp_git_repo):
    """工作区脏（tracked 文件有未提交改动）→ 默认拒绝（exit 1）。
    untracked 文件（如审校 docx 本身）不算脏。"""
    (tmp_git_repo / '.review_state.json').write_text(
        json.dumps({'last_exported_sha': None, 'last_exported_at': None, 'exports': []}),
        encoding='utf-8')
    _commit(tmp_git_repo, 'chapter.md', MIN_MD, 'v1')
    sha2 = _commit(tmp_git_repo, 'chapter.md', MIN_MD_V2, 'v2')

    r = _run_cli('export-review', sha2, '--path', 'chapter.md', cwd=tmp_git_repo)
    assert r.returncode == 0, r.stderr
    docx = tmp_git_repo / f'chapter_{sha2[:7]}.docx'

    # 让 tracked 文件有未提交改动（这才算脏）
    (tmp_git_repo / 'chapter.md').write_text(MIN_MD_V2 + '额外。\n', encoding='utf-8')

    r = _run_cli('import-review', str(docx), '--reviewer', '测试员',
                 cwd=tmp_git_repo)
    assert r.returncode != 0
    assert '工作区' in (r.stderr + r.stdout) or 'dirty' in (r.stderr + r.stdout).lower()
