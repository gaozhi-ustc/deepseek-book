import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_install_md_docx_review_bridge_skill(tmp_path):
    archive = PROJECT_ROOT / 'skills' / 'md-docx-review-bridge.tgz'
    script = PROJECT_ROOT / 'scripts' / 'install-md-docx-review-bridge-skill.sh'
    codex_home = tmp_path / 'codex-home'

    assert archive.exists()
    assert script.exists()

    env = {**os.environ, 'CODEX_HOME': str(codex_home)}
    result = subprocess.run(
        ['bash', str(script)],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout

    skill_dir = codex_home / 'skills' / 'md-docx-review-bridge'
    assert (skill_dir / 'SKILL.md').exists()
    assert (skill_dir / 'references' / 'deepseek-book-review-bridge.md').exists()
    assert (skill_dir / 'scripts' / 'inspect_review_docx.py').exists()

    second = subprocess.run(
        ['bash', str(script)],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert second.returncode != 0
    assert '--force' in (second.stderr + second.stdout)

    forced = subprocess.run(
        ['bash', str(script), '--force'],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert forced.returncode == 0, forced.stderr + forced.stdout
    assert (skill_dir / 'SKILL.md').exists()
