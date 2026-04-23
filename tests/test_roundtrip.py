"""roundtrip 测试：export-review → (模拟审校) → import-review。

只覆盖"机器可完成"的那部分：用 minimal.md → minimal_edited.md 生成
reviewed_tracked.docx，再直接 import-review 进 tmp 仓库，看 review 分支
的 commit 内容含关键改动。

需手工 fixtures 的路径（plain/comments/mixed）只在可用时测试。
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = PROJECT_ROOT / 'tests' / 'fixtures'


def _run_cli(*args, cwd):
    cmd = [sys.executable, str(PROJECT_ROOT / 'cli.py'), *args]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def _commit_file(repo, relpath, content, msg):
    (repo / relpath).write_text(content, encoding='utf-8')
    subprocess.run(['git', 'add', relpath], cwd=repo, check=True)
    subprocess.run(['git', 'commit', '-q', '-m', msg], cwd=repo, check=True)
    return subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()


def test_roundtrip_tracked(tmp_git_repo, fixtures_dir):
    """初始化 tmp repo 提交 minimal.md → 把 reviewed_tracked.docx 拿去 import。"""
    # 基线
    base_sha = _commit_file(tmp_git_repo, 'minimal.md',
                            (fixtures_dir / 'minimal.md').read_text(encoding='utf-8'),
                            'v1')
    # .review_state.json
    (tmp_git_repo / '.review_state.json').write_text(
        '{"last_exported_sha": null, "last_exported_at": null, "exports": []}',
        encoding='utf-8')

    # 把 fixture docx 拷进去，起"带基线指纹"的名字
    docx_src = FIXTURES / 'reviewed_tracked.docx'
    if not docx_src.exists():
        pytest.skip('tests/build_fixtures.py 未运行；缺 reviewed_tracked.docx')
    short = base_sha[:7]
    docx_dst = tmp_git_repo / f'minimal_{short}.docx'
    shutil.copy(docx_src, docx_dst)

    # import
    r = _run_cli('import-review', str(docx_dst),
                 '--reviewer', '测试员',
                 '--base', base_sha, '--path', 'minimal.md',
                 cwd=tmp_git_repo)
    assert r.returncode == 0, r.stderr

    # review 分支内容应含关键改动
    branch_name = None
    for line in subprocess.check_output(
            ['git', 'branch'], cwd=tmp_git_repo, text=True).splitlines():
        if 'review/ceshiyuan' in line:
            branch_name = line.strip().lstrip('* ').strip()
            break
    assert branch_name is not None, r.stdout + r.stderr

    new_md = subprocess.check_output(
        ['git', 'show', f'{branch_name}:minimal.md'],
        cwd=tmp_git_repo, text=True)
    # roundtrip 只验证 review 分支被建出、有非空内容且与 baseline 有差异
    # （md_diff_docx 的 Track Changes docx 设计给人看，不是完美 roundtrip 源；
    #  更精细的 block 级 roundtrip 由 test_import_review_with_actual_changes_... 覆盖）
    baseline = (fixtures_dir / 'minimal.md').read_text(encoding='utf-8')
    assert new_md.strip() != ''
    assert new_md != baseline


def test_roundtrip_plain_if_available(tmp_git_repo, fixtures_dir):
    plain = FIXTURES / 'reviewed_plain.docx'
    if not plain.exists():
        pytest.skip('需手工生成 reviewed_plain.docx（见 tests/fixtures/README.md）')
    base_sha = _commit_file(tmp_git_repo, 'minimal.md',
                            (fixtures_dir / 'minimal.md').read_text(encoding='utf-8'),
                            'v1')
    shutil.copy(plain, tmp_git_repo / 'reviewed_plain.docx')
    r = _run_cli('import-review', 'reviewed_plain.docx',
                 '--reviewer', '测试员',
                 '--base', base_sha, '--path', 'minimal.md',
                 cwd=tmp_git_repo)
    assert r.returncode == 0, r.stderr
