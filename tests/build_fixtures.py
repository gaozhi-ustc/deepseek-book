"""tests/build_fixtures.py — 再生所有可自动合成的 fixtures。

用法：
  python3.14 tests/build_fixtures.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from md_diff_docx import diff_md_files


def main():
    minimal = HERE / 'fixtures' / 'minimal.md'
    edited = HERE / 'fixtures' / 'minimal_edited.md'
    out = HERE / 'fixtures' / 'reviewed_tracked.docx'
    diff_md_files(str(minimal), str(edited), str(out),
                  use_comments=False, author='测试审校者')
    print(f'✅ 生成 {out}')


if __name__ == '__main__':
    main()
