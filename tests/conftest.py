"""Pytest 共享 fixtures。

- tmp_git_repo：在 tmp_path 里 init 一个带初始 commit 的 git 仓库，
  并把 PROJECT_ROOT 的 md_core.py / md_formatter.py / md_diff_docx.py /
  MML2OMML.XSL 拷过去（避免 import 找不到），随后 cd 进去，返回 repo 路径。
"""
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


@pytest.fixture
def tmp_git_repo(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    repo.mkdir()

    # 初始化 git
    _run(['git', 'init', '-q', '-b', 'main'], repo)
    _run(['git', 'config', 'user.email', 'test@example.com'], repo)
    _run(['git', 'config', 'user.name', 'Test'], repo)
    _run(['git', 'config', 'commit.gpgsign', 'false'], repo)

    # 最小 README 作为初始 commit
    (repo / 'README.md').write_text('# test repo\n', encoding='utf-8')
    _run(['git', 'add', 'README.md'], repo)
    _run(['git', 'commit', '-q', '-m', 'init'], repo)

    # 让测试里 import 的模块能找到项目根
    monkeypatch.syspath_prepend(str(PROJECT_ROOT))
    monkeypatch.chdir(repo)

    return repo


@pytest.fixture
def fixtures_dir():
    return PROJECT_ROOT / 'tests' / 'fixtures'
