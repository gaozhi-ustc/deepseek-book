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
