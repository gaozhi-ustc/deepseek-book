# md ↔ docx 审校桥实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在已有 md→docx 工具链（`md_core.py` / `md_formatter.py` / `md_diff_docx.py` / `cli.py`）之上，实现"md commit → 带 Track Changes 的 docx"送审、以及"审校 docx → 写入 review 分支的 commit"回灌。

**Architecture:** 新增 4 个模块（`docx_reader.py`、`docx_to_md.py`、`git_review.py`、`comment_classifier.py`），共享 `md_core.Block` 数据模型（通过追加可选 `revisions`/`comments` 字段向后兼容）。`cli.py` 再挂两个子命令 `export-review` / `import-review`。所有 git 操作用 plumbing（`hash-object` / `mktree` / `commit-tree` / `update-ref`），绝不 `checkout` review 分支，保证 main 工作区不被扰动。旧脚本（`md2docx*.py` 4 个）迁到 `legacy/` 保留历史。

**Tech Stack:** Python 3.10+（项目实际跑 `/opt/homebrew/bin/python3.14`；PEP 604 联合类型必需）、python-docx 1.2、lxml 6、latex2mathml 3.81、新增 anthropic ≥ 0.40 + pypinyin ≥ 0.50 + pytest。可选 libreoffice（公式截图降级）。

**设计 spec：** `docs/superpowers/specs/2026-04-23-md-docx-revision-bridge-design.md`（已冻结，任何偏离先改 spec 再改代码）。

**工作流约定：**
- 严格 TDD：先写失败测试，跑一次确认失败信息符合预期，再写最小实现，再跑通过。
- 每个 Task 结束都 commit，中文 title + `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`。
- 所有命令用 `python3.14` 而不是 `python`/`python3`（`md_core.py` 用 PEP 604 语法，系统默认 3.9 会 `TypeError`）。
- 测试用 `python3.14 -m pytest tests/ -v`。
- 运行前先确认工作区干净：`git status`。

**模块总览：**

```
deepseek-book/
├── cli.py                       # [改] +export-review +import-review
├── md_core.py                   # [改] Block 追加 revisions/comments
├── md_formatter.py              # [不动]
├── md_diff_docx.py              # [不动]
│
├── docx_reader.py               # [新]
├── docx_to_md.py                # [新]
├── git_review.py                # [新]
├── comment_classifier.py        # [新]
│
├── legacy/                      # [新]
│   ├── README.md
│   ├── md2docx.py
│   ├── md2docx_improved.py
│   ├── md2docx_v2.py
│   └── md2docx_latex.py
│
├── requirements.txt             # [新]
├── .review_state.json           # [新] 工具自维护的状态
│
└── tests/
    ├── conftest.py
    ├── fixtures/
    │   ├── minimal.md
    │   ├── minimal_edited.md
    │   ├── reviewed_tracked.docx
    │   ├── reviewed_plain.docx
    │   ├── reviewed_comments.docx
    │   ├── reviewed_mixed.docx
    │   └── README.md
    ├── test_md_core_back_compat.py
    ├── test_git_review.py
    ├── test_docx_reader.py
    ├── test_comment_classifier.py
    ├── test_docx_to_md.py
    ├── test_cli_review.py
    ├── test_roundtrip.py
    ├── build_fixtures.py
    └── smoke.sh
```

---

## Stage A — 准备

### Task 1: 迁移旧脚本到 `legacy/`

**Files:**
- Move (`git mv`): `md2docx.py` → `legacy/md2docx.py`
- Move (`git mv`): `md2docx_improved.py` → `legacy/md2docx_improved.py`
- Move (`git mv`): `md2docx_v2.py` → `legacy/md2docx_v2.py`
- Move (`git mv`): `md2docx_latex.py` → `legacy/md2docx_latex.py`
- Create: `legacy/README.md`

- [ ] **Step 1: 验证工作区干净**

Run: `git status`
Expected: `nothing to commit, working tree clean`

（若非 clean，先 `git stash` 或 commit 再继续，不允许混入不相关改动。）

- [ ] **Step 2: 建立 legacy 目录并迁移 4 个旧脚本（保留 git 历史）**

Run:
```bash
mkdir -p legacy
git mv md2docx.py          legacy/md2docx.py
git mv md2docx_improved.py legacy/md2docx_improved.py
git mv md2docx_v2.py       legacy/md2docx_v2.py
git mv md2docx_latex.py    legacy/md2docx_latex.py
```

Expected: 4 个 `renamed:` 条目出现在 `git status`。

- [ ] **Step 3: 写 `legacy/README.md`**

```markdown
# legacy/

本目录收纳历史脚本，功能已被主线代码覆盖，**不要修改、不要引用**。仅作为历史追溯保留。

主线替代：

| 旧脚本 | 当前等价 |
|--------|----------|
| `md2docx.py`, `md2docx_improved.py`, `md2docx_v2.py`, `md2docx_latex.py` | `md_core.py` + `md_formatter.py` + `cli.py convert` |

如需恢复某段历史逻辑，请复制一份到主线模块中再改，不要直接 import `legacy/*`。
```

- [ ] **Step 4: 确认主线功能未受迁移影响**

Run: `python3.14 cli.py convert chapter3_new.md -o /tmp/chapter3_check.docx`
Expected: 正常输出 `✅ 文档已保存: /tmp/chapter3_check.docx` 与公式统计（413/413）；无 import 报错。

- [ ] **Step 5: commit**

```bash
git add legacy/
git commit -m "$(cat <<'EOF'
refactor: 迁移历史 md2docx 脚本到 legacy/

主线功能已由 md_core.py + md_formatter.py + cli.py convert 覆盖，
将四个历史脚本归档到 legacy/ 并加 README 警示，避免新代码误引用。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 扩展 `md_core.Block` — 新增 Revision/Comment 字段

**Files:**
- Modify: `md_core.py:30-78`
- Create: `tests/__init__.py`（空文件）
- Create: `tests/test_md_core_back_compat.py`

- [ ] **Step 1: 写失败测试 — 老式构造（不传新字段）仍然成功**

Create `tests/__init__.py` 空文件。

Create `tests/test_md_core_back_compat.py`:
```python
"""确保在 md_core.Block 追加 revisions/comments 字段后，
所有历史构造点（md_core / md_formatter / md_diff_docx 内部）仍能不传新字段而成立，
且新字段默认为空 list。"""

from md_core import (
    HeadingBlock, ParagraphBlock, EquationBlock,
    TableBlock, CodeBlock, FigureBlock, ListBlock, BlankBlock,
    Revision, Comment,
)


def test_paragraph_block_backwards_compatible():
    b = ParagraphBlock(text='hello', raw='hello')
    assert b.text == 'hello'
    assert b.revisions == []
    assert b.comments == []


def test_heading_block_backwards_compatible():
    b = HeadingBlock(level=2, text='标题', raw='## 标题')
    assert b.level == 2
    assert b.revisions == []
    assert b.comments == []


def test_all_blocks_have_revisions_and_comments():
    blocks = [
        HeadingBlock(level=1, text='a', raw='# a'),
        ParagraphBlock(text='p', raw='p'),
        EquationBlock(latex='x=1', raw='$$x=1$$'),
        TableBlock(header=['A'], rows=[['1']], caption='', raw=''),
        CodeBlock(code='x=1', language='python', title='', raw=''),
        FigureBlock(alt='alt', path='x.png', caption='', raw=''),
        ListBlock(items=['a', 'b'], ordered=False, raw=''),
        BlankBlock(),
    ]
    for b in blocks:
        assert hasattr(b, 'revisions')
        assert hasattr(b, 'comments')
        assert b.revisions == []
        assert b.comments == []


def test_revision_dataclass_shape():
    r = Revision(kind='ins', text='new', author='张三',
                 date='2026-04-23T10:00:00Z', rev_id=1)
    assert r.kind == 'ins'
    assert r.text == 'new'
    assert r.author == '张三'


def test_comment_dataclass_shape():
    c = Comment(comment_id=0, author='李四',
                date='2026-04-23T10:00:00Z',
                text='这句不通', anchor_text='此处',
                anchor_range=(0, 2))
    assert c.comment_id == 0
    assert c.anchor_range == (0, 2)


def test_blocks_accept_revisions_and_comments_kwargs():
    r = Revision(kind='del', text='old', author='a', date='d', rev_id=1)
    c = Comment(comment_id=0, author='a', date='d',
                text='b', anchor_text='b', anchor_range=(0, 1))
    b = ParagraphBlock(text='t', raw='t', revisions=[r], comments=[c])
    assert b.revisions == [r]
    assert b.comments == [c]
```

- [ ] **Step 2: 跑失败测试**

Run: `python3.14 -m pytest tests/test_md_core_back_compat.py -v`
Expected: 所有测试 `ERROR`（`ImportError: cannot import name 'Revision'`）或 `FAILED`。

- [ ] **Step 3: 修改 `md_core.py` — 新增 Revision/Comment 并追加字段**

在 `md_core.py` 顶部 `from typing import List, Optional` 行改为：
```python
from typing import List, Optional, Literal, Tuple
```

在 `Block 数据模型` 注释块之后、`HeadingBlock` 之前插入：
```python
@dataclass
class Revision:
    kind: Literal['ins', 'del']
    text: str
    author: str
    date: str          # ISO 8601
    rev_id: int


@dataclass
class Comment:
    comment_id: int
    author: str
    date: str
    text: str                        # 批注正文
    anchor_text: str                 # 批注锚点原文
    anchor_range: Tuple[int, int]    # Block text 内字符偏移 [start, end)
```

然后修改所有 Block 的 dataclass 定义，给每个（除 `BlankBlock` 外）追加两个字段，必须带默认 `field(default_factory=list)`（位置在已有字段之后，作为纯新增字段保证向后兼容）。

以 `HeadingBlock` 为例，改成：
```python
@dataclass
class HeadingBlock:
    level: int
    text: str
    raw: str
    revisions: List[Revision] = field(default_factory=list)
    comments: List[Comment]   = field(default_factory=list)
```

对 `ParagraphBlock` / `EquationBlock` / `TableBlock` / `CodeBlock` / `FigureBlock` / `ListBlock` 做同样追加。`BlankBlock` 也加（保持对称，代价为零）：
```python
@dataclass
class BlankBlock:
    raw: str = ''
    revisions: List[Revision] = field(default_factory=list)
    comments: List[Comment]   = field(default_factory=list)
```

- [ ] **Step 4: 跑测试通过**

Run: `python3.14 -m pytest tests/test_md_core_back_compat.py -v`
Expected: 6 passed。

- [ ] **Step 5: 回归测试 — 确保现有 md→docx 仍然工作**

Run: `python3.14 cli.py convert chapter3_new.md -o /tmp/chapter3_check2.docx`
Expected: `✅ 文档已保存` + 公式统计 413/413（成功数字不变）。

- [ ] **Step 6: commit**

```bash
git add md_core.py tests/
git commit -m "$(cat <<'EOF'
feat(md_core): 追加 Revision / Comment 数据类与 Block.revisions / Block.comments 字段

回灌侧需要把 docx 的 track-changes 和 comments 挂回 Block IR。
新增字段用 field(default_factory=list) 默认值，保证所有旧构造点零改动。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 项目骨架 — `requirements.txt` / `.review_state.json` / `tests/conftest.py`

**Files:**
- Create: `requirements.txt`
- Create: `.review_state.json`
- Create: `.gitignore`（修改：加 `review/attachments/` 行）
- Create: `tests/conftest.py`
- Create: `tests/test_review_state.py`

- [ ] **Step 1: 写失败测试 — review_state 初始结构**

Create `tests/test_review_state.py`:
```python
"""确认 .review_state.json 合法且可被 json.load，含标准字段。"""
import json
import os


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def test_review_state_is_valid_json():
    path = os.path.join(PROJECT_ROOT, '.review_state.json')
    assert os.path.exists(path), '.review_state.json 必须存在'
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, dict)
    assert data.get('last_exported_sha') is None or isinstance(data['last_exported_sha'], str)
    assert data.get('last_exported_at') is None or isinstance(data['last_exported_at'], str)
    assert 'exports' in data
    assert isinstance(data['exports'], list)


def test_requirements_txt_lists_new_deps():
    path = os.path.join(PROJECT_ROOT, 'requirements.txt')
    assert os.path.exists(path)
    content = open(path).read()
    assert 'python-docx' in content
    assert 'lxml' in content
    assert 'latex2mathml' in content
    assert 'anthropic' in content
    assert 'pypinyin' in content
```

- [ ] **Step 2: 跑失败测试**

Run: `python3.14 -m pytest tests/test_review_state.py -v`
Expected: `FAILED` — 两个文件都不存在。

- [ ] **Step 3: 创建 `.review_state.json`**

```json
{
  "last_exported_sha": null,
  "last_exported_at": null,
  "exports": []
}
```

- [ ] **Step 4: 创建 `requirements.txt`**

```
python-docx>=1.2.0
lxml>=4.9
latex2mathml>=3.78
anthropic>=0.40
pypinyin>=0.50
pytest>=7.0
```

- [ ] **Step 5: 追加 `.gitignore`**

在 `.gitignore` 末尾追加（确保新行）：
```
# md-docx 审校桥运行时产物
review/
tests/__pycache__/
tests/fixtures/tmp/
*.docx.base
```

（`review/` 是 import-review 产出的公式截图/片段 docx 暂存目录；review 分支是 ref 不影响 .gitignore。）

- [ ] **Step 6: 创建 `tests/conftest.py`**

```python
"""Pytest 共享 fixtures。

- tmp_git_repo：在 tmp_path 里 init 一个带初始 commit 的 git 仓库，
  并把 PROJECT_ROOT 的 md_core.py / md_formatter.py / md_diff_docx.py /
  MML2OMML.XSL 拷过去（避免 import 找不到），随后 cd 进去，返回 repo 路径。
"""
import os
import shutil
import subprocess
import sys
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
```

- [ ] **Step 7: 跑测试通过**

Run: `python3.14 -m pytest tests/test_review_state.py tests/test_md_core_back_compat.py -v`
Expected: 8 passed。

- [ ] **Step 8: 安装新依赖**

Run:
```bash
python3.14 -m pip install --user --break-system-packages anthropic pypinyin pytest
```

Expected: `Successfully installed anthropic-x.y.z pypinyin-x.y.z pytest-x.y.z`（版本允许差异）。

- [ ] **Step 9: commit**

```bash
git add requirements.txt .review_state.json .gitignore tests/
git commit -m "$(cat <<'EOF'
chore: 新增 requirements.txt / .review_state.json / tests 骨架

requirements.txt 固化运行时依赖；.review_state.json 初始为空 exports 列表；
tests/conftest.py 提供 tmp_git_repo fixture，所有 git_review 测试共用。
回归测试 tests/test_md_core_back_compat.py 已通过。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Stage B — `git_review.py` git 封装层

**模块职责（全部在 `git_review.py`，一个文件）：**
- `read_at(sha, path, repo='.') -> str`：`git show sha:path` 的封装。
- `resolve_range(arg, repo='.', state_path='.review_state.json') -> (base_sha, head_sha)`：解析 `<commit>` / `<base>..<head>` / `--since-last-review`。
- `stamp_docx_metadata(docx_path, source_git_commit, source_base_commit, source_path, exported_at)`：写 `docProps/custom.xml`。
- `read_docx_metadata(docx_path) -> dict`：回读同一份 custom.xml。
- `resolve_baseline(docx_path, repo='.', cli_base=None, cli_path=None) -> (base_sha, source_path, source_kind)`：4 级回退。
- `detect_reviewer(cli_reviewer, reviewed_docx_path) -> (display_name, slug)`。
- `commit_to_review_branch(repo, reviewer_slug, reviewer_name, base_sha, md_path, new_md_bytes, commit_message, docx_filename) -> (branch_ref, new_commit_sha)`：用 plumbing 命令，不切 HEAD。
- `update_review_state(state_path, sha, exported_at, file_name, base_sha)`：维护 `.review_state.json`。

---

### Task 4: `read_at()` + `resolve_range()`

**Files:**
- Create: `git_review.py`
- Create: `tests/test_git_review.py`

- [ ] **Step 1: 写失败测试 — `read_at()` 读历史内容**

Create `tests/test_git_review.py`:
```python
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
```

- [ ] **Step 2: 跑失败测试**

Run: `python3.14 -m pytest tests/test_git_review.py -v`
Expected: 全部 `ERROR`（模块不存在）。

- [ ] **Step 3: 实现 `git_review.py` 的 `read_at` + `resolve_range`**

```python
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
```

- [ ] **Step 4: 跑测试通过**

Run: `python3.14 -m pytest tests/test_git_review.py -v`
Expected: 6 passed。

- [ ] **Step 5: commit**

```bash
git add git_review.py tests/test_git_review.py
git commit -m "$(cat <<'EOF'
feat(git_review): read_at + resolve_range

封装 git show 与范围解析（单 commit / dotdot / --since-last-review），
统一抛 GitReviewError，全部测试走真实 git（tmp 仓库）。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `stamp_docx_metadata()` + `read_docx_metadata()`

**Files:**
- Modify: `git_review.py`（追加函数与常量）
- Modify: `tests/test_git_review.py`（追加测试）

- [ ] **Step 1: 写失败测试**

在 `tests/test_git_review.py` 末尾追加：
```python
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
```

- [ ] **Step 2: 跑失败测试**

Run: `python3.14 -m pytest tests/test_git_review.py -v -k metadata`
Expected: 3 个用例 ERROR（import 失败）。

- [ ] **Step 3: 在 `git_review.py` 末尾追加 metadata 函数**

```python
# ──────────────────────────────────────────────────────────
# docx custom.xml 元数据
# ──────────────────────────────────────────────────────────

import zipfile
import shutil
from lxml import etree

_CUSTOM_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/custom-properties'
_VT_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes'
_PROPS_FMTID = '{D5CDD505-2E9C-101B-9397-08002B2CF9AE}'
_CT_NS = 'http://schemas.openxmlformats.org/package/2006/content-types'
_RELS_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'

_METADATA_KEYS = ('SourceGitCommit', 'SourceBaseCommit',
                  'SourcePath', 'ReviewExportedAt')


def _build_custom_xml(props: dict) -> bytes:
    nsmap = {None: _CUSTOM_NS, 'vt': _VT_NS}
    root = etree.Element('{%s}Properties' % _CUSTOM_NS, nsmap=nsmap)
    pid = 2  # pid 1 是保留值
    for name in _METADATA_KEYS:
        if name not in props:
            continue
        p = etree.SubElement(root, '{%s}property' % _CUSTOM_NS)
        p.set('fmtid', _PROPS_FMTID)
        p.set('pid', str(pid))
        p.set('name', name)
        v = etree.SubElement(p, '{%s}lpwstr' % _VT_NS)
        v.text = props[name]
        pid += 1
    return etree.tostring(root, xml_declaration=True,
                          encoding='UTF-8', standalone=True)


def stamp_docx_metadata(docx_path: str,
                        source_git_commit: str,
                        source_base_commit: str,
                        source_path: str,
                        exported_at: str) -> None:
    """把 4 项元数据写入 docx 的 docProps/custom.xml（必要时也更新
    [Content_Types].xml 与 _rels/.rels，使 Word 能识别该 part）。"""
    props = {
        'SourceGitCommit':   source_git_commit,
        'SourceBaseCommit':  source_base_commit,
        'SourcePath':        source_path,
        'ReviewExportedAt':  exported_at,
    }
    new_xml = _build_custom_xml(props)

    tmp_path = docx_path + '.tmp'
    with zipfile.ZipFile(docx_path, 'r') as zin, \
         zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as zout:
        names = set(zin.namelist())

        # 1. 复制除 custom.xml / [Content_Types].xml / _rels/.rels 外的全部文件
        for item in zin.infolist():
            if item.filename in ('docProps/custom.xml',
                                 '[Content_Types].xml',
                                 '_rels/.rels'):
                continue
            zout.writestr(item, zin.read(item.filename))

        # 2. 写新的 custom.xml
        zout.writestr('docProps/custom.xml', new_xml)

        # 3. 更新 [Content_Types].xml 确保声明 custom.xml
        ct_src = zin.read('[Content_Types].xml')
        ct_root = etree.fromstring(ct_src)
        want_pn = '/docProps/custom.xml'
        already_declared = any(
            o.get('PartName') == want_pn
            for o in ct_root.findall('{%s}Override' % _CT_NS)
        )
        if not already_declared:
            o = etree.SubElement(ct_root, '{%s}Override' % _CT_NS)
            o.set('PartName', want_pn)
            o.set('ContentType',
                  'application/vnd.openxmlformats-officedocument.custom-properties+xml')
        zout.writestr('[Content_Types].xml',
                      etree.tostring(ct_root, xml_declaration=True,
                                     encoding='UTF-8', standalone=True))

        # 4. 更新 _rels/.rels 确保有 Relationship 指向 custom.xml
        rels_src = zin.read('_rels/.rels')
        rels_root = etree.fromstring(rels_src)
        want_target = 'docProps/custom.xml'
        have = any(
            r.get('Target') == want_target
            for r in rels_root.findall('{%s}Relationship' % _RELS_NS)
        )
        if not have:
            existing_ids = [r.get('Id') for r in rels_root
                            if r.get('Id') and r.get('Id').startswith('rId')]
            max_id = max((int(x[3:]) for x in existing_ids), default=0)
            rel = etree.SubElement(rels_root, '{%s}Relationship' % _RELS_NS)
            rel.set('Id', f'rId{max_id + 1}')
            rel.set('Type', 'http://schemas.openxmlformats.org/'
                           'officeDocument/2006/relationships/custom-properties')
            rel.set('Target', want_target)
        zout.writestr('_rels/.rels',
                      etree.tostring(rels_root, xml_declaration=True,
                                     encoding='UTF-8', standalone=True))

        _ = names  # suppress unused

    shutil.move(tmp_path, docx_path)


def read_docx_metadata(docx_path: str) -> dict:
    """回读 docProps/custom.xml 的 4 个键；若 part 不存在返回 {}"""
    try:
        with zipfile.ZipFile(docx_path, 'r') as z:
            if 'docProps/custom.xml' not in z.namelist():
                return {}
            data = z.read('docProps/custom.xml')
    except zipfile.BadZipFile as e:
        raise GitReviewError(f'不是合法的 docx（zip）文件: {docx_path}') from e

    root = etree.fromstring(data)
    result = {}
    for p in root.findall('{%s}property' % _CUSTOM_NS):
        name = p.get('name')
        val_el = p.find('{%s}lpwstr' % _VT_NS)
        if name in _METADATA_KEYS and val_el is not None and val_el.text:
            result[name] = val_el.text
    return result
```

- [ ] **Step 4: 跑测试通过**

Run: `python3.14 -m pytest tests/test_git_review.py -v`
Expected: 9 passed。

- [ ] **Step 5: commit**

```bash
git add git_review.py tests/test_git_review.py
git commit -m "$(cat <<'EOF'
feat(git_review): stamp_docx_metadata / read_docx_metadata

把送审溯源信息（SourceGitCommit/SourceBaseCommit/SourcePath/ReviewExportedAt）
写入 docProps/custom.xml，并正确注册 Content_Types 与 rels 以便回读。
stamp 具备幂等性，覆盖旧值而非追加。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: `resolve_baseline()` — 四级回退

**Files:**
- Modify: `git_review.py`
- Modify: `tests/test_git_review.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_git_review.py` 末尾追加：
```python
# ── resolve_baseline ──────────────────────────────────────
import re
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
```

- [ ] **Step 2: 跑失败测试**

Run: `python3.14 -m pytest tests/test_git_review.py -v -k baseline`
Expected: 7 个用例 ERROR。

- [ ] **Step 3: 实现 `resolve_baseline()`**

在 `git_review.py` 末尾追加：

```python
# ──────────────────────────────────────────────────────────
# resolve_baseline 四级回退
# ──────────────────────────────────────────────────────────

_FILENAME_SHA_RE = re.compile(r'_([0-9a-f]{7,40})\.docx$', re.IGNORECASE)


def _try_rev_parse(ref: str, repo: str) -> Optional[str]:
    try:
        return _rev_parse(ref, repo=repo)
    except GitReviewError:
        return None


def _path_exists_at(sha: str, path: str, repo: str) -> bool:
    try:
        _git(['cat-file', '-e', f'{sha}:{path}'], repo=repo)
        return True
    except GitReviewError:
        return False


def resolve_baseline(docx_path: str,
                     repo: str = '.',
                     cli_base: Optional[str] = None,
                     cli_path: Optional[str] = None) -> Tuple[str, str, str]:
    """四级回退确定基线：
      1. custom.xml 中的 SourceGitCommit / SourcePath
      2. 文件名匹配 *_<sha7+>.docx；path 走 cli_path
      3. sidecar 文件 <docx_path>.base（首行 sha）；path 走 cli_path
      4. cli_base + cli_path
    全都失败 → GitReviewError。
    返回 (base_sha_full40, source_path, source_kind)。
    """
    import re as _re  # 避免被 Task 5 的 import 污染
    _ = _re

    # 1. metadata
    try:
        meta = read_docx_metadata(docx_path)
    except GitReviewError:
        meta = {}
    if meta.get('SourceGitCommit') and meta.get('SourcePath'):
        sha = _try_rev_parse(meta['SourceGitCommit'], repo=repo)
        if sha is not None:
            if not _path_exists_at(sha, meta['SourcePath'], repo=repo):
                raise GitReviewError(
                    f"metadata 的 SourceGitCommit={meta['SourceGitCommit'][:7]} "
                    f"在仓库里存在，但其 SourcePath={meta['SourcePath']} 不存在；"
                    "sha 与 path 不匹配")
            return sha, meta['SourcePath'], 'metadata'

    # 2. 文件名
    m = _FILENAME_SHA_RE.search(os.path.basename(docx_path))
    if m and cli_path:
        sha = _try_rev_parse(m.group(1), repo=repo)
        if sha is not None and _path_exists_at(sha, cli_path, repo=repo):
            return sha, cli_path, 'filename'

    # 3. sidecar
    sidecar = docx_path + '.base'
    if os.path.exists(sidecar) and cli_path:
        with open(sidecar, 'r', encoding='utf-8') as f:
            content = f.readline().strip()
        sha = _try_rev_parse(content, repo=repo)
        if sha is not None and _path_exists_at(sha, cli_path, repo=repo):
            return sha, cli_path, 'sidecar'

    # 4. CLI
    if cli_base and cli_path:
        sha = _try_rev_parse(cli_base, repo=repo)
        if sha is not None and _path_exists_at(sha, cli_path, repo=repo):
            return sha, cli_path, 'cli'

    raise GitReviewError(
        'resolve_baseline 四级回退全部失败：metadata/filename/sidecar/cli 都未命中。'
        '请使用 --base <sha> --path <relpath> 明确指定。'
    )
```

- [ ] **Step 4: 跑测试通过**

Run: `python3.14 -m pytest tests/test_git_review.py -v`
Expected: 16 passed。

- [ ] **Step 5: commit**

```bash
git add git_review.py tests/test_git_review.py
git commit -m "$(cat <<'EOF'
feat(git_review): resolve_baseline 四级回退

依次尝试 custom.xml / 文件名 *_<sha>.docx / sidecar .base / CLI 参数。
metadata 匹配到 sha 但 path 不存在时报错而非继续回退，避免静默用错基线。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: `detect_reviewer()` — 中文名 → slug

**Files:**
- Modify: `git_review.py`
- Modify: `tests/test_git_review.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_git_review.py` 末尾追加：
```python
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
```

- [ ] **Step 2: 跑失败测试**

Run: `python3.14 -m pytest tests/test_git_review.py -v -k reviewer`
Expected: 4 ERROR。

- [ ] **Step 3: 实现 `detect_reviewer()`**

在 `git_review.py` 末尾追加：
```python
# ──────────────────────────────────────────────────────────
# detect_reviewer
# ──────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    """中文 → 拼音（全拼，不带声调，小写），英文 → kebab-case。"""
    from pypinyin import lazy_pinyin
    import unicodedata as _ud

    # 先把中文转拼音，英文保持
    parts = lazy_pinyin(name)
    joined = ''.join(parts).strip().lower()

    # 保留字母数字与连字符，空白改连字符，其余丢掉
    out = []
    for ch in joined:
        cat = _ud.category(ch)
        if ch.isalnum():
            out.append(ch)
        elif ch.isspace():
            out.append('-')
    slug = ''.join(out)

    # 合并连续连字符
    while '--' in slug:
        slug = slug.replace('--', '-')
    slug = slug.strip('-')
    return slug or 'unknown'


def _majority_docx_ins_author(docx_path: str) -> Optional[str]:
    """从 docx 的 <w:ins w:author> 中取出现次数最多的一个，无则 None。"""
    try:
        with zipfile.ZipFile(docx_path, 'r') as z:
            if 'word/document.xml' not in z.namelist():
                return None
            data = z.read('word/document.xml')
    except (zipfile.BadZipFile, KeyError):
        return None

    root = etree.fromstring(data)
    w_ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    from collections import Counter
    c = Counter()
    for ins in root.iter(f'{{{w_ns}}}ins'):
        a = ins.get(f'{{{w_ns}}}author')
        if a:
            c[a] += 1
    if not c:
        return None
    return c.most_common(1)[0][0]


def detect_reviewer(cli_reviewer: Optional[str],
                    reviewed_docx_path: str) -> Tuple[str, str]:
    """返回 (display_name, slug)。

    优先级：CLI > docx <w:ins w:author> 多数值 > 'unknown'
    """
    if cli_reviewer and cli_reviewer.strip():
        name = cli_reviewer.strip()
        return name, _slugify(name)

    if reviewed_docx_path and os.path.exists(reviewed_docx_path):
        a = _majority_docx_ins_author(reviewed_docx_path)
        if a:
            return a, _slugify(a)

    return 'unknown', 'unknown'
```

- [ ] **Step 4: 跑测试通过**

Run: `python3.14 -m pytest tests/test_git_review.py -v`
Expected: 20 passed。

- [ ] **Step 5: commit**

```bash
git add git_review.py tests/test_git_review.py
git commit -m "$(cat <<'EOF'
feat(git_review): detect_reviewer — 中文名走 pypinyin 生成分支 slug

优先级 CLI > docx <w:ins w:author> 多数值 > 'unknown'。
slugify 对非中文保留 ASCII 并以 - 连接，生成稳定可读的分支后缀。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: `commit_to_review_branch()` — plumbing 命令建分支

**Files:**
- Modify: `git_review.py`
- Modify: `tests/test_git_review.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_git_review.py` 末尾追加：
```python
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
```

- [ ] **Step 2: 跑失败测试**

Run: `python3.14 -m pytest tests/test_git_review.py -v -k "review_branch or review_state"`
Expected: 3 ERROR。

- [ ] **Step 3: 实现 `commit_to_review_branch()` + `update_review_state()`**

在 `git_review.py` 末尾追加：
```python
# ──────────────────────────────────────────────────────────
# commit_to_review_branch — 不切 HEAD 地建分支并写 commit
# ──────────────────────────────────────────────────────────

def _write_blob_from_bytes(data: bytes, repo: str) -> str:
    out = _git(['hash-object', '-w', '--stdin'],
               repo=repo, input_bytes=data)
    return out.decode('ascii').strip()


def _build_new_tree(base_commit_sha: str, override_path: str,
                    new_blob_sha: str, repo: str) -> str:
    """以 base_commit 的 tree 为模板，把 override_path 的 blob 替换成
    new_blob_sha，写出新 tree sha。

    用临时 GIT_INDEX_FILE + read-tree + update-index --cacheinfo + write-tree，
    原生支持任意深度的路径，且不干扰主索引。
    """
    import tempfile as _tempfile
    fd, idx_path = _tempfile.mkstemp(suffix='.gitidx')
    os.close(fd)
    os.remove(idx_path)  # read-tree 需要文件不存在
    env = {'GIT_INDEX_FILE': idx_path}
    try:
        _git(['read-tree', base_commit_sha], repo=repo, env=env)
        _git(['update-index', '--add', '--cacheinfo',
              f'100644,{new_blob_sha},{override_path}'],
             repo=repo, env=env)
        out = _git(['write-tree'], repo=repo, env=env)
        return out.decode('ascii').strip()
    finally:
        if os.path.exists(idx_path):
            try:
                os.remove(idx_path)
            except OSError:
                pass


def _ref_exists(ref: str, repo: str) -> bool:
    try:
        _git(['show-ref', '--verify', '--quiet', ref], repo=repo)
        return True
    except GitReviewError:
        return False


def _pick_branch_ref(slug: str, date_str: str, repo: str) -> str:
    base = f'refs/heads/review/{slug}-{date_str}'
    if not _ref_exists(base, repo=repo):
        return base
    for n in range(2, 100):
        cand = f'{base}-{n}'
        if not _ref_exists(cand, repo=repo):
            return cand
    raise GitReviewError(
        f'review 分支命名冲突超过 99 次：{base}-* 全部已存在')


def commit_to_review_branch(*,
                            repo: str,
                            reviewer_slug: str,
                            reviewer_name: str,
                            base_sha: str,
                            md_path: str,
                            new_md_bytes: bytes,
                            commit_message: str,
                            docx_filename: str,
                            date_str: str) -> Tuple[str, str]:
    """用 plumbing 写入 review/<slug>-<date>[-<n>] 分支上的一个 commit，
    不 checkout / 不动工作区。

    返回 (branch_ref, new_commit_sha)。
    """
    _ = docx_filename  # 仅用于调用方组 message；函数内不直接落盘

    # 1. blob
    blob_sha = _write_blob_from_bytes(new_md_bytes, repo=repo)

    # 2. tree（在 base 的 tree 基础上替换 md_path）
    tree_sha = _build_new_tree(base_sha, md_path, blob_sha, repo=repo)

    # 3. commit
    env = {
        'GIT_AUTHOR_NAME':    reviewer_name,
        'GIT_AUTHOR_EMAIL':   f'{reviewer_slug}@review.local',
        'GIT_COMMITTER_NAME':  'md-docx-bridge',
        'GIT_COMMITTER_EMAIL': 'bridge@review.local',
    }
    out = _git(['commit-tree', tree_sha, '-p', base_sha, '-m', commit_message],
               repo=repo, env=env)
    new_sha = out.decode('ascii').strip()

    # 4. 选分支 ref 并 update-ref
    branch_ref = _pick_branch_ref(reviewer_slug, date_str, repo=repo)
    _git(['update-ref', branch_ref, new_sha], repo=repo)
    return branch_ref, new_sha


# ──────────────────────────────────────────────────────────
# update_review_state
# ──────────────────────────────────────────────────────────

def update_review_state(state_path: str, *,
                        sha: str,
                        exported_at: str,
                        file_name: str,
                        base_sha: str) -> None:
    """追加 export 记录并把 last_exported_sha 指向新 sha。"""
    if os.path.exists(state_path):
        with open(state_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        data = {'last_exported_sha': None, 'last_exported_at': None, 'exports': []}

    data.setdefault('exports', [])
    data['exports'].append({'sha': sha, 'file': file_name, 'base': base_sha})
    data['last_exported_sha'] = sha
    data['last_exported_at'] = exported_at

    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write('\n')
```

- [ ] **Step 4: 跑测试通过**

Run: `python3.14 -m pytest tests/test_git_review.py -v`
Expected: 23 passed。

- [ ] **Step 5: commit**

```bash
git add git_review.py tests/test_git_review.py
git commit -m "$(cat <<'EOF'
feat(git_review): commit_to_review_branch + update_review_state

用 hash-object / mktree --batch / commit-tree / update-ref 四步 plumbing
在 review/<slug>-<date>[-N] 上写 commit，不动 HEAD。同名分支存在时自动递增后缀。
update_review_state 更新 .review_state.json 记录送审历史。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Stage C — `docx_reader.py` docx → Block IR

**模块职责：** 读 docx（`.zip` 解开 `word/document.xml` + `word/comments.xml`），逐 block 生成 `md_core.Block`，挂上 `revisions` / `comments`。块的文本字段存"接受所有修订后的最终文本"。

**共同辅助函数（放 `docx_reader.py` 顶部）：**
- `_parse_document_xml(docx_path) -> etree._Element`
- `_parse_comments_xml(docx_path) -> dict[int, Comment_partial]`（不含 anchor_range；由正文解析时填充）
- `_extract_run_text(r_el)`：读 `<w:t>` / `<w:delText>` 文本
- `_extract_paragraph_accepted_text(p_el)`：遍历段落内全部 run，`<w:del>` 跳过其内部文本，`<w:ins>` 计入

**公共 Block IR 返回语义：** `read_docx(path) -> List[Block]` 返回平铺 block 列表，顺序与 `word/document.xml` 一致。

---

### Task 9: paragraph block — 带 revisions

**Files:**
- Create: `docx_reader.py`（只实现到 paragraph）
- Create: `tests/test_docx_reader.py`
- Create: `tests/fixtures/build_min_docx.py`（生成简单 docx 的工具脚本，测试专用）

- [ ] **Step 1: 先写"受控 docx 构造器"供测试用**

Create `tests/fixtures/build_min_docx.py`:
```python
"""造带精确 OOXML 结构（track changes / comments / 表格 / 公式等）的
最小 docx 供单测使用。不是给终端用户的。

函数按『造一个含特定元素的 docx』粒度提供，测试里直接调用。
"""
import zipfile
import io
from datetime import datetime, timezone

W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


_MIN_CONTENT_TYPES = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>
</Types>
'''

_MIN_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
'''

_MIN_DOC_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>
</Relationships>
'''


def write_docx(path: str, document_xml_body: str,
               comments_xml: str | None = None,
               media: dict | None = None,
               extra_rels: str | None = None) -> None:
    """
    document_xml_body 直接是 <w:body> 内部的 XML（不含 <w:document> 外壳）。
    comments_xml 为完整 <w:comments>...</w:comments>，可为 None。
    media: dict[内部路径 → bytes]
    """
    document_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body>
{document_xml_body}
  </w:body>
</w:document>'''

    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', _MIN_CONTENT_TYPES)
        z.writestr('_rels/.rels', _MIN_RELS)
        z.writestr('word/_rels/document.xml.rels',
                   extra_rels or _MIN_DOC_RELS)
        z.writestr('word/document.xml', document_xml)
        if comments_xml is not None:
            z.writestr('word/comments.xml', comments_xml)
        if media:
            for subpath, data in media.items():
                z.writestr(f'word/media/{subpath}', data)


def make_paragraph(text: str, *,
                   ins_spans: list[tuple[int, int, str, str]] = None,
                   del_spans: list[tuple[int, int, str, str]] = None) -> str:
    """
    构造一个 <w:p>，text 为接受全部 ins / 全部 del 仍保留状态后的
    "最终"文本；ins_spans / del_spans 是基于 text 字符偏移的标注列表
    [(start, end, author, date)]。

    输出的 runs 会按顺序穿插 <w:r>（普通）/ <w:ins>（整段）/ <w:del>（整段删除）。
    del_spans 的文本从 text 切片；删除的部分不出现在 "accepted" 可见文本里，
    但此函数接受的 text 是已经排除 del 的"visible"文本 — 参见下例。

    为简化：两种 spans 互斥，不重叠。
    """
    spans = []
    for s, e, a, d in (ins_spans or []):
        spans.append((s, e, 'ins', a, d))
    for s, e, a, d in (del_spans or []):
        spans.append((s, e, 'del', a, d))
    spans.sort()

    # 把 text 按 spans 切成段；text 里不包含 del 的文本（del 是单独插回）
    parts = []
    pos = 0
    for (s, e, kind, a, d) in spans:
        if pos < s:
            parts.append(('plain', text[pos:s], None, None))
        parts.append((kind, text[s:e], a, d))
        pos = e
    if pos < len(text):
        parts.append(('plain', text[pos:], None, None))

    out = ['<w:p>']
    rev_id = 1000
    for (kind, t, a, d) in parts:
        if kind == 'plain':
            out.append(f'<w:r><w:t xml:space="preserve">{t}</w:t></w:r>')
        elif kind == 'ins':
            rev_id += 1
            out.append(
                f'<w:ins w:id="{rev_id}" w:author="{a}" w:date="{d}">'
                f'<w:r><w:t xml:space="preserve">{t}</w:t></w:r>'
                '</w:ins>')
        elif kind == 'del':
            rev_id += 1
            out.append(
                f'<w:del w:id="{rev_id}" w:author="{a}" w:date="{d}">'
                f'<w:r><w:delText xml:space="preserve">{t}</w:delText></w:r>'
                '</w:del>')
    out.append('</w:p>')
    return '\n'.join(out)


def make_heading(level: int, text: str) -> str:
    return (f'<w:p><w:pPr><w:pStyle w:val="Heading{level}"/></w:pPr>'
            f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>')
```

- [ ] **Step 2: 写失败测试（paragraph）**

Create `tests/test_docx_reader.py`:
```python
"""docx_reader.py 的测试，fixtures 由 tests/fixtures/build_min_docx.py 就地构造。"""
from pathlib import Path

import pytest

from md_core import ParagraphBlock
from docx_reader import read_docx
from tests.fixtures.build_min_docx import write_docx, make_paragraph


def test_read_plain_paragraph(tmp_path):
    body = make_paragraph('这是一段纯文本。')
    docx = tmp_path / 'p.docx'
    write_docx(str(docx), body)

    blocks = read_docx(str(docx))
    paras = [b for b in blocks if isinstance(b, ParagraphBlock)]
    assert len(paras) == 1
    assert paras[0].text == '这是一段纯文本。'
    assert paras[0].revisions == []


def test_read_paragraph_with_ins_accepts_ins_in_text(tmp_path):
    """接受 ins：text 应包含 ins 的内容。"""
    body = make_paragraph('前缀XYZ后缀',
                          ins_spans=[(2, 5, '张三', '2026-04-23T00:00:00Z')])
    docx = tmp_path / 'p.docx'
    write_docx(str(docx), body)

    blocks = read_docx(str(docx))
    paras = [b for b in blocks if isinstance(b, ParagraphBlock)]
    p = paras[0]
    assert p.text == '前缀XYZ后缀'
    assert len(p.revisions) == 1
    r = p.revisions[0]
    assert r.kind == 'ins'
    assert r.text == 'XYZ'
    assert r.author == '张三'


def test_read_paragraph_with_del_excludes_del_from_text(tmp_path):
    """删除：text 应只含未删除部分；revisions 记录 del 的原文。"""
    # 构造时 text 是 "留下" 的部分；del 段是额外要标注为被删的 "掉" 字
    body_pieces = [
        '<w:p>',
        '<w:r><w:t xml:space="preserve">留下</w:t></w:r>',
        '<w:del w:id="2001" w:author="李四" w:date="2026-04-23T00:00:00Z">'
        '<w:r><w:delText xml:space="preserve">掉</w:delText></w:r>'
        '</w:del>',
        '<w:r><w:t xml:space="preserve">的文本</w:t></w:r>',
        '</w:p>',
    ]
    body = '\n'.join(body_pieces)
    docx = tmp_path / 'p.docx'
    write_docx(str(docx), body)

    blocks = read_docx(str(docx))
    paras = [b for b in blocks if isinstance(b, ParagraphBlock)]
    p = paras[0]
    assert p.text == '留下的文本'
    assert len(p.revisions) == 1
    r = p.revisions[0]
    assert r.kind == 'del'
    assert r.text == '掉'
    assert r.author == '李四'


def test_read_bad_zip_raises(tmp_path):
    bad = tmp_path / 'bad.docx'
    bad.write_text('not a zip', encoding='utf-8')
    from docx_reader import DocxReaderError
    with pytest.raises(DocxReaderError):
        read_docx(str(bad))
```

- [ ] **Step 3: 跑失败测试**

Run: `python3.14 -m pytest tests/test_docx_reader.py -v`
Expected: 4 ERROR（`ModuleNotFoundError: No module named 'docx_reader'`）。

- [ ] **Step 4: 实现 `docx_reader.py` paragraph 部分**

```python
"""docx_reader.py — 读 docx，按 word/document.xml 顺序产出 md_core.Block 列表。

覆盖 Block 类型：paragraph / heading / list / code / table / equation /
figure / blank，带 revisions / comments。

用 lxml 直接读 OOXML；python-docx 不足以读到 w:ins / w:del / m:oMath。
"""
import os
import re
import zipfile
from typing import List, Optional

from lxml import etree

from md_core import (
    Block, Revision, Comment,
    HeadingBlock, ParagraphBlock, EquationBlock,
    TableBlock, CodeBlock, FigureBlock, ListBlock, BlankBlock,
)


W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
M_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
A_NS = 'http://schemas.openxmlformats.org/drawingml/2006/main'
PIC_NS = 'http://schemas.openxmlformats.org/drawingml/2006/picture'

W = '{%s}' % W_NS
M = '{%s}' % M_NS


class DocxReaderError(RuntimeError):
    pass


# ──────────────────────────────────────────────────────────
# 打开 docx 并返回 document/comments/rels/media 相关 bytes
# ──────────────────────────────────────────────────────────

def _open_docx(path: str) -> dict:
    try:
        z = zipfile.ZipFile(path, 'r')
    except (zipfile.BadZipFile, OSError) as e:
        raise DocxReaderError(f'{path} 不是合法的 docx（zip）文件: {e}') from e

    with z:
        names = set(z.namelist())
        doc = z.read('word/document.xml') if 'word/document.xml' in names else None
        comments = z.read('word/comments.xml') if 'word/comments.xml' in names else None
        rels = z.read('word/_rels/document.xml.rels') \
            if 'word/_rels/document.xml.rels' in names else None
        media = {}
        for n in names:
            if n.startswith('word/media/'):
                media[n[len('word/media/'):]] = z.read(n)

    if doc is None:
        raise DocxReaderError(f'{path} 没有 word/document.xml')
    return {'document': doc, 'comments': comments, 'rels': rels, 'media': media}


# ──────────────────────────────────────────────────────────
# run 级文本与 revisions 抽取
# ──────────────────────────────────────────────────────────

def _text_of_w_t(r_el) -> str:
    parts = []
    for t in r_el.findall(f'{W}t'):
        parts.append(t.text or '')
    return ''.join(parts)


def _text_of_w_del_text(r_el) -> str:
    parts = []
    for t in r_el.findall(f'{W}delText'):
        parts.append(t.text or '')
    return ''.join(parts)


def _paragraph_accepted_text_and_revisions(p_el):
    """遍历段落的孩子节点，按顺序拼『接受所有 ins、丢弃所有 del』的最终文本，
    并收集 Revision 列表。

    返回 (text, revisions, anchor_offsets)。anchor_offsets 是 dict[comment_id, (start, end)]
    （end 可能在后续段落延续，这里仅记录本段内的开始/结束）。
    """
    text_parts: List[str] = []
    revisions: List[Revision] = []
    comment_spans: dict = {}
    comment_open: dict = {}

    def _emit(text: str):
        text_parts.append(text)

    def _len():
        return sum(len(x) for x in text_parts)

    for child in p_el:
        tag = etree.QName(child).localname
        ns = etree.QName(child).namespace

        if ns != W_NS:
            continue

        if tag == 'r':
            _emit(_text_of_w_t(child))
        elif tag == 'ins':
            ins_text = ''
            for r in child.findall(f'{W}r'):
                ins_text += _text_of_w_t(r)
            _emit(ins_text)
            revisions.append(Revision(
                kind='ins', text=ins_text,
                author=child.get(f'{W}author', ''),
                date=child.get(f'{W}date', ''),
                rev_id=int(child.get(f'{W}id', '0') or 0),
            ))
        elif tag == 'del':
            del_text = ''
            for r in child.findall(f'{W}r'):
                del_text += _text_of_w_del_text(r)
            revisions.append(Revision(
                kind='del', text=del_text,
                author=child.get(f'{W}author', ''),
                date=child.get(f'{W}date', ''),
                rev_id=int(child.get(f'{W}id', '0') or 0),
            ))
            # 注意：del 不写入 accepted text
        elif tag == 'commentRangeStart':
            cid = int(child.get(f'{W}id', '0') or 0)
            comment_open[cid] = _len()
        elif tag == 'commentRangeEnd':
            cid = int(child.get(f'{W}id', '0') or 0)
            if cid in comment_open:
                comment_spans[cid] = (comment_open.pop(cid), _len())
        elif tag == 'commentReference':
            # 仅指向位置（无范围）的批注
            cid = int(child.get(f'{W}id', '0') or 0)
            if cid not in comment_spans:
                comment_spans[cid] = (_len(), _len())

    return ''.join(text_parts), revisions, comment_spans


# ──────────────────────────────────────────────────────────
# read_docx 主入口（先实现 paragraph）
# ──────────────────────────────────────────────────────────

def read_docx(path: str) -> List[Block]:
    """读 docx 返回 Block 列表。"""
    bundle = _open_docx(path)
    root = etree.fromstring(bundle['document'])
    body = root.find(f'{W}body')
    if body is None:
        return []

    blocks: List[Block] = []
    for child in body:
        tag = etree.QName(child).localname
        ns = etree.QName(child).namespace
        if ns != W_NS:
            continue

        if tag == 'p':
            blocks.append(_read_paragraph(child))
        elif tag == 'sectPr':
            continue
        # 后续任务会追加 table / sdt 等
    return blocks


def _read_paragraph(p_el) -> Block:
    text, revisions, _ = _paragraph_accepted_text_and_revisions(p_el)
    if not text.strip():
        return BlankBlock(raw='')
    return ParagraphBlock(text=text, raw=text,
                          revisions=revisions, comments=[])
```

- [ ] **Step 5: 跑测试通过**

Run: `python3.14 -m pytest tests/test_docx_reader.py -v`
Expected: 4 passed。

- [ ] **Step 6: commit**

```bash
git add docx_reader.py tests/test_docx_reader.py tests/fixtures/
git commit -m "$(cat <<'EOF'
feat(docx_reader): 初版 read_docx — paragraph + track-changes

读 word/document.xml 顺序产出 ParagraphBlock，
w:ins 计入 accepted text + 记为 Revision(kind='ins')，
w:del 仅记为 Revision(kind='del')、其 delText 不计入 accepted text。
tests/fixtures/build_min_docx.py 就地造精确 OOXML fixtures，避免依赖手工 docx。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: heading / list / code

**Files:**
- Modify: `docx_reader.py`
- Modify: `tests/test_docx_reader.py`
- Modify: `tests/fixtures/build_min_docx.py`（已有 `make_heading`；补 `make_list_item` / `make_code_block`）

- [ ] **Step 1: 追加 fixture 构造器**

在 `tests/fixtures/build_min_docx.py` 末尾追加：
```python
def make_list_item(text: str, *, ordered: bool = False, num_id: int = 1) -> str:
    """w:numPr 引用 w:numId — 我们用约定 numId=1 为无序，numId=2 为有序，
    上层只需读 numId 判断是否是列表。"""
    nid = 1 if not ordered else 2
    _ = num_id
    return (f'<w:p><w:pPr><w:numPr>'
            f'<w:ilvl w:val="0"/><w:numId w:val="{nid}"/></w:numPr></w:pPr>'
            f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>')


def make_code_block(code_lines: list[str]) -> str:
    """约定：pStyle=Code / HTMLPreformatted / Courier 之一即视作 code；
    我们这里用 pStyle="Code"，docx_reader 会识别。
    多行会产生多个 <w:p>。"""
    paras = []
    for line in code_lines:
        paras.append(
            f'<w:p><w:pPr><w:pStyle w:val="Code"/></w:pPr>'
            f'<w:r><w:rPr><w:rFonts w:ascii="Courier New"/></w:rPr>'
            f'<w:t xml:space="preserve">{line}</w:t></w:r></w:p>'
        )
    return '\n'.join(paras)
```

- [ ] **Step 2: 写失败测试**

在 `tests/test_docx_reader.py` 末尾追加：
```python
from md_core import HeadingBlock, ListBlock, CodeBlock
from tests.fixtures.build_min_docx import (
    make_heading, make_list_item, make_code_block,
)


def test_read_heading_levels(tmp_path):
    body = '\n'.join([
        make_heading(1, '章标题'),
        make_heading(2, '节标题'),
        make_heading(3, '小节'),
    ])
    docx = tmp_path / 'h.docx'
    write_docx(str(docx), body)
    blocks = read_docx(str(docx))
    hs = [b for b in blocks if isinstance(b, HeadingBlock)]
    assert len(hs) == 3
    assert (hs[0].level, hs[0].text) == (1, '章标题')
    assert (hs[1].level, hs[1].text) == (2, '节标题')
    assert (hs[2].level, hs[2].text) == (3, '小节')


def test_read_unordered_list_merges_adjacent_items(tmp_path):
    body = '\n'.join([
        make_list_item('第一条', ordered=False),
        make_list_item('第二条', ordered=False),
        make_list_item('第三条', ordered=False),
    ])
    docx = tmp_path / 'l.docx'
    write_docx(str(docx), body)
    blocks = read_docx(str(docx))
    lists = [b for b in blocks if isinstance(b, ListBlock)]
    assert len(lists) == 1
    assert lists[0].ordered is False
    assert lists[0].items == ['第一条', '第二条', '第三条']


def test_read_ordered_list(tmp_path):
    body = '\n'.join([
        make_list_item('A', ordered=True),
        make_list_item('B', ordered=True),
    ])
    docx = tmp_path / 'l.docx'
    write_docx(str(docx), body)
    blocks = read_docx(str(docx))
    lists = [b for b in blocks if isinstance(b, ListBlock)]
    assert len(lists) == 1
    assert lists[0].ordered is True
    assert lists[0].items == ['A', 'B']


def test_read_code_block_merges_adjacent_paragraphs(tmp_path):
    body = make_code_block([
        'def foo():',
        '    return 42',
        '',
    ])
    docx = tmp_path / 'c.docx'
    write_docx(str(docx), body)
    blocks = read_docx(str(docx))
    codes = [b for b in blocks if isinstance(b, CodeBlock)]
    assert len(codes) == 1
    assert codes[0].code == 'def foo():\n    return 42\n'
```

- [ ] **Step 3: 跑失败测试**

Run: `python3.14 -m pytest tests/test_docx_reader.py -v`
Expected: 4 新增用例 FAIL（当前 `_read_paragraph` 把 heading/list/code 都当成普通段落）。

- [ ] **Step 4: 在 `docx_reader.py` 增加 heading/list/code 识别**

在 `_read_paragraph` 之前新增辅助函数：
```python
def _pstyle(p_el) -> Optional[str]:
    pPr = p_el.find(f'{W}pPr')
    if pPr is None:
        return None
    s = pPr.find(f'{W}pStyle')
    return s.get(f'{W}val') if s is not None else None


def _heading_level(style: Optional[str]) -> Optional[int]:
    if not style:
        return None
    m = re.match(r'(?i)heading\s*([1-6])$', style)
    if m:
        return int(m.group(1))
    return None


def _num_id(p_el) -> Optional[int]:
    pPr = p_el.find(f'{W}pPr')
    if pPr is None:
        return None
    numPr = pPr.find(f'{W}numPr')
    if numPr is None:
        return None
    nid = numPr.find(f'{W}numId')
    if nid is None:
        return None
    try:
        return int(nid.get(f'{W}val'))
    except (TypeError, ValueError):
        return None


def _is_code_paragraph(p_el) -> bool:
    style = _pstyle(p_el)
    if style and style.lower() in ('code', 'sourcecode', 'htmlpreformatted'):
        return True
    # 全部 run 使用 Courier 字体 → 视为代码
    runs = p_el.findall(f'{W}r')
    if not runs:
        return False
    mono = 0
    for r in runs:
        rPr = r.find(f'{W}rPr')
        if rPr is None:
            return False
        rfonts = rPr.find(f'{W}rFonts')
        if rfonts is None:
            return False
        font = (rfonts.get(f'{W}ascii') or '').lower()
        if 'courier' in font or 'consolas' in font or 'monaco' in font:
            mono += 1
    return mono == len(runs)
```

然后把 `read_docx` 主循环改为带"合并"状态的版本：
```python
def read_docx(path: str) -> List[Block]:
    bundle = _open_docx(path)
    root = etree.fromstring(bundle['document'])
    body = root.find(f'{W}body')
    if body is None:
        return []

    blocks: List[Block] = []
    # 合并状态
    list_buf_items: List[str] = []
    list_buf_ordered: Optional[bool] = None
    code_buf_lines: List[str] = []

    def _flush_list():
        nonlocal list_buf_items, list_buf_ordered
        if list_buf_items:
            blocks.append(ListBlock(items=list_buf_items,
                                    ordered=bool(list_buf_ordered),
                                    raw=''))
            list_buf_items = []
            list_buf_ordered = None

    def _flush_code():
        nonlocal code_buf_lines
        if code_buf_lines:
            blocks.append(CodeBlock(code='\n'.join(code_buf_lines) + '\n',
                                    language='', title='', raw=''))
            code_buf_lines = []

    for child in body:
        tag = etree.QName(child).localname
        ns = etree.QName(child).namespace
        if ns != W_NS:
            continue

        if tag != 'p':
            _flush_list(); _flush_code()
            if tag == 'sectPr':
                continue
            continue  # 非段落元素后续任务处理

        style = _pstyle(child)
        hlevel = _heading_level(style)
        nid = _num_id(child)
        is_code = _is_code_paragraph(child)
        text, revisions, _comments_raw = _paragraph_accepted_text_and_revisions(child)

        if hlevel is not None:
            _flush_list(); _flush_code()
            blocks.append(HeadingBlock(level=hlevel, text=text, raw=text,
                                       revisions=revisions, comments=[]))
            continue

        if nid is not None:
            _flush_code()
            ordered = (nid == 2)  # 约定；真实 docx 里需查 numbering.xml
            if list_buf_ordered is None:
                list_buf_ordered = ordered
            if list_buf_ordered != ordered:
                _flush_list()
                list_buf_ordered = ordered
            list_buf_items.append(text)
            continue

        if is_code:
            _flush_list()
            code_buf_lines.append(text)
            continue

        _flush_list(); _flush_code()
        if not text.strip():
            blocks.append(BlankBlock(raw=''))
        else:
            blocks.append(ParagraphBlock(text=text, raw=text,
                                         revisions=revisions, comments=[]))

    _flush_list(); _flush_code()
    return blocks
```

- [ ] **Step 5: 跑测试通过**

Run: `python3.14 -m pytest tests/test_docx_reader.py -v`
Expected: 8 passed。

- [ ] **Step 6: commit**

```bash
git add docx_reader.py tests/
git commit -m "$(cat <<'EOF'
feat(docx_reader): 识别 heading / list / code 三类块

- Heading 依据 pStyle="HeadingN"（1..6）
- List 依据 w:numPr/w:numId（约定 1=无序 2=有序），相邻同类合并
- Code 依据 pStyle=Code 或全部 run 为 Courier/Consolas/Monaco 字体

合并缓冲使 list / code 的多个 <w:p> 归到同一个 Block。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: table

**Files:**
- Modify: `docx_reader.py`
- Modify: `tests/test_docx_reader.py`
- Modify: `tests/fixtures/build_min_docx.py`

- [ ] **Step 1: 追加 `make_table` fixture 构造器**

在 `tests/fixtures/build_min_docx.py` 末尾追加：
```python
def make_table(header: list[str], rows: list[list[str]]) -> str:
    def cell(text):
        return (f'<w:tc><w:p><w:r><w:t xml:space="preserve">{text}'
                '</w:t></w:r></w:p></w:tc>')
    all_rows = [header] + rows
    out = ['<w:tbl>']
    for row in all_rows:
        out.append('<w:tr>')
        for c in row:
            out.append(cell(c))
        out.append('</w:tr>')
    out.append('</w:tbl>')
    return '\n'.join(out)
```

- [ ] **Step 2: 写失败测试**

在 `tests/test_docx_reader.py` 末尾追加：
```python
from md_core import TableBlock
from tests.fixtures.build_min_docx import make_table


def test_read_table_basic(tmp_path):
    body = make_table(
        header=['列A', '列B', '列C'],
        rows=[['1', '2', '3'], ['x', 'y', 'z']],
    )
    docx = tmp_path / 't.docx'
    write_docx(str(docx), body)
    blocks = read_docx(str(docx))
    tables = [b for b in blocks if isinstance(b, TableBlock)]
    assert len(tables) == 1
    t = tables[0]
    assert t.header == ['列A', '列B', '列C']
    assert t.rows == [['1', '2', '3'], ['x', 'y', 'z']]


def test_read_table_with_empty_cells(tmp_path):
    body = make_table(
        header=['A', 'B'],
        rows=[['', 'b']],
    )
    docx = tmp_path / 't.docx'
    write_docx(str(docx), body)
    blocks = read_docx(str(docx))
    tables = [b for b in blocks if isinstance(b, TableBlock)]
    assert len(tables) == 1
    assert tables[0].rows == [['', 'b']]
```

- [ ] **Step 3: 跑失败测试**

Run: `python3.14 -m pytest tests/test_docx_reader.py -v -k table`
Expected: 2 FAIL（当前循环 `continue`。没有返回 TableBlock）。

- [ ] **Step 4: 在 `read_docx` 里识别 `<w:tbl>`**

在 `read_docx` 主循环的 `if tag != 'p':` 分支里加表格处理：
```python
        if tag != 'p':
            _flush_list(); _flush_code()
            if tag == 'tbl':
                blocks.append(_read_table(child))
                continue
            if tag == 'sectPr':
                continue
            continue
```

并新增 `_read_table`：
```python
def _read_table(tbl_el) -> TableBlock:
    rows_xml = tbl_el.findall(f'{W}tr')
    rows = []
    for tr in rows_xml:
        cells = []
        for tc in tr.findall(f'{W}tc'):
            # 合并同一 cell 内多个 <w:p> 的 accepted 文本
            texts = []
            for p in tc.findall(f'{W}p'):
                text, _, _ = _paragraph_accepted_text_and_revisions(p)
                texts.append(text)
            cells.append('\n'.join(x for x in texts if x))
        rows.append(cells)

    if not rows:
        return TableBlock(header=[], rows=[], caption='', raw='')
    header = rows[0]
    body_rows = rows[1:]
    return TableBlock(header=header, rows=body_rows, caption='', raw='')
```

- [ ] **Step 5: 跑测试通过**

Run: `python3.14 -m pytest tests/test_docx_reader.py -v`
Expected: 10 passed。

- [ ] **Step 6: commit**

```bash
git add docx_reader.py tests/
git commit -m "$(cat <<'EOF'
feat(docx_reader): 识别 <w:tbl> → TableBlock

第一行作 header，其余为 rows；单元格内多个 <w:p> 用换行拼接；caption 留空
（送审时 md_formatter 会重新编号，审校结果不预置 caption）。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: equation（OMML 指纹）

**Files:**
- Modify: `docx_reader.py`
- Modify: `tests/test_docx_reader.py`
- Modify: `tests/fixtures/build_min_docx.py`

- [ ] **Step 1: 追加 fixture 构造器**

在 `tests/fixtures/build_min_docx.py` 末尾追加：
```python
def make_equation_paragraph(omml_xml: str) -> str:
    """omml_xml 是 <m:oMath>...</m:oMath> 片段，会包进 <m:oMathPara>。"""
    return (f'<w:p><m:oMathPara xmlns:m="http://schemas.openxmlformats.org/'
            f'officeDocument/2006/math">{omml_xml}</m:oMathPara></w:p>')


SIMPLE_OMATH_X_EQ_1 = (
    '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
    '<m:r><m:t>x=1</m:t></m:r>'
    '</m:oMath>'
)

SIMPLE_OMATH_X_EQ_2 = (
    '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
    '<m:r><m:t>x=2</m:t></m:r>'
    '</m:oMath>'
)
```

- [ ] **Step 2: 写失败测试**

在 `tests/test_docx_reader.py` 末尾追加：
```python
from md_core import EquationBlock
from tests.fixtures.build_min_docx import (
    make_equation_paragraph,
    SIMPLE_OMATH_X_EQ_1, SIMPLE_OMATH_X_EQ_2,
)


def test_read_block_equation(tmp_path):
    body = make_equation_paragraph(SIMPLE_OMATH_X_EQ_1)
    docx = tmp_path / 'e.docx'
    write_docx(str(docx), body)
    blocks = read_docx(str(docx))
    eqs = [b for b in blocks if isinstance(b, EquationBlock)]
    assert len(eqs) == 1
    # latex 字段暂时留作指纹载体：OMML 规范化字符串
    # 我们不做 OMML→LaTeX，所以 .latex 以 @omml: 前缀表示尚未 LaTeX 化
    assert eqs[0].latex.startswith('@omml:')


def test_equation_fingerprint_distinguishes_different_omml(tmp_path):
    from docx_reader import equation_fingerprint
    import lxml.etree as ET
    f1 = equation_fingerprint(ET.fromstring(SIMPLE_OMATH_X_EQ_1))
    f2 = equation_fingerprint(ET.fromstring(SIMPLE_OMATH_X_EQ_2))
    assert len(f1) == 64  # sha256 hex
    assert f1 != f2


def test_equation_fingerprint_canonical_ignores_rpr_noise(tmp_path):
    """同一个公式但带了字体 rPr 属性，指纹应相同。"""
    from docx_reader import equation_fingerprint
    import lxml.etree as ET

    noisy = (
        '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'
        ' xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<m:r>'
        '<w:rPr><w:rFonts w:ascii="Cambria Math"/></w:rPr>'
        '<m:t xml:space="preserve">x=1</m:t>'
        '</m:r>'
        '</m:oMath>'
    )
    f_clean = equation_fingerprint(ET.fromstring(SIMPLE_OMATH_X_EQ_1))
    f_noisy = equation_fingerprint(ET.fromstring(noisy))
    assert f_clean == f_noisy
```

- [ ] **Step 3: 跑失败测试**

Run: `python3.14 -m pytest tests/test_docx_reader.py -v -k equation`
Expected: 3 用例 FAIL/ERROR。

- [ ] **Step 4: 在 `docx_reader.py` 中实现 `equation_fingerprint` 并在主循环识别公式**

新增函数（放 `_read_table` 之后）：
```python
# ──────────────────────────────────────────────────────────
# 公式指纹
# ──────────────────────────────────────────────────────────

import hashlib
import copy

def _canonicalize_omml(omath_el) -> bytes:
    """返回规范化 OMML 的 c14n 字节串。
    规范化做法：
      - 复制原树，剥除 <w:rPr>（字体等样式属性不影响公式内容）
      - 公式内容以 m:t 文本与结构为主；后续发现误判时可再细化剥法
      - xml c14n
    """
    cloned = copy.deepcopy(omath_el)
    # 删 <w:rPr>
    for rpr in list(cloned.iter(f'{W}rPr')):
        parent = rpr.getparent()
        if parent is not None:
            parent.remove(rpr)
    # c14n
    return etree.tostring(cloned, method='c14n')


def equation_fingerprint(omath_el) -> str:
    """公式内容指纹，不随 rPr 字体属性变化。"""
    return hashlib.sha256(_canonicalize_omml(omath_el)).hexdigest()
```

然后在 `read_docx` 的段落处理分支里检测公式：
```python
        # 在 `_paragraph_accepted_text_and_revisions` 之前检查是否是公式段
        # 检测：段落内出现 m:oMath 或 m:oMathPara → EquationBlock
        omaths = child.findall(f'.//{{{M_NS}}}oMath')
        if omaths:
            _flush_list(); _flush_code()
            # 用第一个 oMath 生成指纹，串联多个公式段时后续任务处理
            fp = equation_fingerprint(omaths[0])
            raw_xml = etree.tostring(omaths[0]).decode('utf-8')
            blocks.append(EquationBlock(latex=f'@omml:{fp}',
                                        raw=raw_xml,
                                        revisions=[], comments=[]))
            continue
```

**把这段插入在 `hlevel is not None:` 之前**（公式优先判断，避免误识别为普通段落）。

- [ ] **Step 5: 跑测试通过**

Run: `python3.14 -m pytest tests/test_docx_reader.py -v`
Expected: 13 passed。

- [ ] **Step 6: commit**

```bash
git add docx_reader.py tests/
git commit -m "$(cat <<'EOF'
feat(docx_reader): 识别 equation + 规范化 OMML 指纹

段落含 <m:oMath> 时产出 EquationBlock.latex='@omml:<sha256>'，
规范化前剥除 w:rPr 字体噪声后 c14n，使同一公式的不同字体属性得到相同指纹。
暂不做 OMML→LaTeX 反向（按 spec §5.2 / §6.2 走占位方案）。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: figure — 抽 word/media + sha256

**Files:**
- Modify: `docx_reader.py`
- Modify: `tests/test_docx_reader.py`
- Modify: `tests/fixtures/build_min_docx.py`

- [ ] **Step 1: 追加 fixture**

在 `tests/fixtures/build_min_docx.py` 末尾追加：
```python
def make_figure_paragraph(rel_id: str, alt: str = '') -> str:
    """构造含 drawing 的段落，引用 rel_id 指向 word/media/xxx。"""
    return (
        '<w:p>'
        '<w:r><w:drawing>'
        '<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
        f'<wp:docPr id="1" name="Picture" descr="{alt}"/>'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:blipFill>'
        f'<a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="{rel_id}"/>'
        '</pic:blipFill>'
        '</pic:pic>'
        '</a:graphicData>'
        '</a:graphic>'
        '</wp:inline>'
        '</w:drawing></w:r>'
        '</w:p>'
    )


def make_doc_rels_with_image(rel_id: str, media_file: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        f'  <Relationship Id="{rel_id}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        f'Target="media/{media_file}"/>\n'
        '</Relationships>\n'
    )
```

- [ ] **Step 2: 写失败测试**

在 `tests/test_docx_reader.py` 末尾追加：
```python
from md_core import FigureBlock
from tests.fixtures.build_min_docx import (
    make_figure_paragraph, make_doc_rels_with_image,
)

PNG_1x1 = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\x00'
    b'\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
)


def test_read_figure_with_media(tmp_path):
    body = make_figure_paragraph('rId7', alt='示意图')
    rels = make_doc_rels_with_image('rId7', 'sample.png')
    docx = tmp_path / 'f.docx'
    write_docx(str(docx), body,
               media={'sample.png': PNG_1x1},
               extra_rels=rels)
    blocks = read_docx(str(docx))
    figs = [b for b in blocks if isinstance(b, FigureBlock)]
    assert len(figs) == 1
    fb = figs[0]
    assert fb.alt == '示意图'
    # path 暂以 @media:<filename>:<sha256> 表示（docx_to_md 阶段再解析为真实 md 路径）
    assert fb.path.startswith('@media:sample.png:')
    assert len(fb.path.split(':')[-1]) == 64


def test_read_figure_missing_rel_falls_back_to_alt_only(tmp_path):
    # 没提供 rels 中对应的 id → path 空，alt 保留
    body = make_figure_paragraph('rIdX', alt='孤立图')
    docx = tmp_path / 'f.docx'
    write_docx(str(docx), body)  # 使用默认 rels（没有 rIdX 项）
    blocks = read_docx(str(docx))
    figs = [b for b in blocks if isinstance(b, FigureBlock)]
    assert len(figs) == 1
    assert figs[0].alt == '孤立图'
    assert figs[0].path == ''
```

- [ ] **Step 3: 跑失败测试**

Run: `python3.14 -m pytest tests/test_docx_reader.py -v -k figure`
Expected: 2 用例 FAIL（当前没有 FigureBlock 识别）。

- [ ] **Step 4: 在 `docx_reader.py` 识别图片段并抽取媒体**

新增辅助：
```python
def _parse_document_rels(rels_bytes: Optional[bytes]) -> dict:
    """返回 {rId: 内部路径（去 word/ 前缀）}"""
    if not rels_bytes:
        return {}
    root = etree.fromstring(rels_bytes)
    ns = 'http://schemas.openxmlformats.org/package/2006/relationships'
    out = {}
    for rel in root.findall(f'{{{ns}}}Relationship'):
        out[rel.get('Id')] = rel.get('Target')
    return out


def _find_figure_blips(p_el) -> List[dict]:
    """返回段落内所有图片的 {rId, alt} 列表。"""
    wp_ns = 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
    a_ns = A_NS
    r_ns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'

    result = []
    for blip in p_el.iter(f'{{{a_ns}}}blip'):
        rid = blip.get(f'{{{r_ns}}}embed')
        alt = ''
        # 找该 blip 最近的 <wp:docPr descr/title>
        ancestor = blip.getparent()
        while ancestor is not None:
            # wp:inline / wp:anchor
            docpr = ancestor.find(f'{{{wp_ns}}}docPr')
            if docpr is not None:
                alt = docpr.get('descr') or docpr.get('title') or ''
                break
            ancestor = ancestor.getparent()
        result.append({'rId': rid, 'alt': alt})
    return result
```

在 `read_docx` 主循环里，段落处理路径在"公式识别"之后追加"图片识别"：
```python
        figs = _find_figure_blips(child)
        if figs:
            _flush_list(); _flush_code()
            rels = _parse_document_rels(bundle.get('rels'))
            for fig in figs:
                target = rels.get(fig['rId'], '')
                # target 形如 'media/sample.png'
                if target.startswith('media/'):
                    filename = target[len('media/'):]
                else:
                    filename = os.path.basename(target) if target else ''
                data = bundle['media'].get(filename)
                if data is not None:
                    sha = hashlib.sha256(data).hexdigest()
                    path = f'@media:{filename}:{sha}'
                else:
                    path = ''
                blocks.append(FigureBlock(alt=fig['alt'], path=path,
                                          caption='', raw='',
                                          revisions=[], comments=[]))
            continue
```

（位置：紧跟公式识别分支之后，在 heading/list/code/paragraph 分类之前。）

- [ ] **Step 5: 跑测试通过**

Run: `python3.14 -m pytest tests/test_docx_reader.py -v`
Expected: 15 passed。

- [ ] **Step 6: commit**

```bash
git add docx_reader.py tests/
git commit -m "$(cat <<'EOF'
feat(docx_reader): 识别 figure — blip rId → word/media 二进制 + sha256

path 以 @media:<filename>:<sha256> 形式承载内部图片指纹，
docx_to_md 在回灌时再根据是否已存在于 typora-user-images/ 决定落盘与 md 路径。
alt 从 wp:docPr 的 descr/title 提取，找不到返回空串且 path=''。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 14: comments（含 anchor 定位）

**Files:**
- Modify: `docx_reader.py`
- Modify: `tests/test_docx_reader.py`
- Modify: `tests/fixtures/build_min_docx.py`

- [ ] **Step 1: 追加 fixture — 带批注的段落**

在 `tests/fixtures/build_min_docx.py` 末尾追加：
```python
def make_paragraph_with_comment(before: str, anchor: str, after: str,
                                 comment_id: int) -> str:
    return (
        '<w:p>'
        f'<w:r><w:t xml:space="preserve">{before}</w:t></w:r>'
        f'<w:commentRangeStart w:id="{comment_id}"/>'
        f'<w:r><w:t xml:space="preserve">{anchor}</w:t></w:r>'
        f'<w:commentRangeEnd w:id="{comment_id}"/>'
        f'<w:r><w:commentReference w:id="{comment_id}"/></w:r>'
        f'<w:r><w:t xml:space="preserve">{after}</w:t></w:r>'
        '</w:p>'
    )


def make_comments_xml(entries: list[dict]) -> str:
    """entries: [{id, author, date, text}]"""
    ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    items = []
    for e in entries:
        items.append(
            f'  <w:comment w:id="{e["id"]}" w:author="{e["author"]}" '
            f'w:date="{e["date"]}" w:initials="">'
            f'<w:p><w:r><w:t xml:space="preserve">{e["text"]}</w:t></w:r></w:p>'
            f'</w:comment>'
        )
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<w:comments xmlns:w="{ns}">\n' +
            '\n'.join(items) + '\n</w:comments>\n')
```

- [ ] **Step 2: 写失败测试**

在 `tests/test_docx_reader.py` 末尾追加：
```python
from tests.fixtures.build_min_docx import (
    make_paragraph_with_comment, make_comments_xml,
)


def test_read_paragraph_with_one_comment(tmp_path):
    body = make_paragraph_with_comment(
        before='前段', anchor='此处', after='后段', comment_id=0)
    cxml = make_comments_xml([{
        'id': 0, 'author': '王五',
        'date': '2026-04-23T00:00:00Z', 'text': '这句不通',
    }])
    docx = tmp_path / 'c.docx'
    write_docx(str(docx), body, comments_xml=cxml)
    blocks = read_docx(str(docx))
    paras = [b for b in blocks if isinstance(b, ParagraphBlock)]
    assert len(paras) == 1
    p = paras[0]
    assert p.text == '前段此处后段'
    assert len(p.comments) == 1
    c = p.comments[0]
    assert c.comment_id == 0
    assert c.author == '王五'
    assert c.text == '这句不通'
    assert c.anchor_text == '此处'
    assert c.anchor_range == (2, 4)


def test_read_paragraph_with_pointless_comment_reference(tmp_path):
    """只有 commentReference、没有 range：anchor_range 指向同一点。"""
    body = (
        '<w:p>'
        '<w:r><w:t xml:space="preserve">一整段</w:t></w:r>'
        '<w:r><w:commentReference w:id="7"/></w:r>'
        '</w:p>'
    )
    cxml = make_comments_xml([{
        'id': 7, 'author': '赵六',
        'date': '2026-04-23T00:00:00Z', 'text': '通篇评论',
    }])
    docx = tmp_path / 'c.docx'
    write_docx(str(docx), body, comments_xml=cxml)
    blocks = read_docx(str(docx))
    p = [b for b in blocks if isinstance(b, ParagraphBlock)][0]
    assert len(p.comments) == 1
    c = p.comments[0]
    assert c.anchor_text == ''
    assert c.anchor_range == (3, 3)
```

- [ ] **Step 3: 跑失败测试**

Run: `python3.14 -m pytest tests/test_docx_reader.py -v -k comment`
Expected: 2 FAIL。

- [ ] **Step 4: 在 `docx_reader.py` 解析 comments.xml 并回填**

新增函数：
```python
def _parse_comments_bundle(comments_bytes: Optional[bytes]) -> dict:
    """返回 {comment_id: {author, date, text}}"""
    if not comments_bytes:
        return {}
    root = etree.fromstring(comments_bytes)
    out = {}
    for c in root.findall(f'{W}comment'):
        cid = int(c.get(f'{W}id', '0') or 0)
        # 把所有 w:t 文本拼起来
        text_parts = []
        for t in c.iter(f'{W}t'):
            text_parts.append(t.text or '')
        out[cid] = {
            'author': c.get(f'{W}author', ''),
            'date': c.get(f'{W}date', ''),
            'text': ''.join(text_parts),
        }
    return out
```

改 `_read_paragraph` 调用点 — 由于段落路径已经合并到 `read_docx` 主循环，改主循环里 `paragraph / heading / ...` 流程：

在 `read_docx` 开头读取 comments bundle：
```python
    comments_map = _parse_comments_bundle(bundle.get('comments'))
```

在段落文本与 revisions 抽取之后、分类为 heading/list/... 之前插入：
```python
        # 把本段 comment_spans 映射为 Comment 列表
        block_comments: List[Comment] = []
        for cid, (s, e) in _comments_raw.items():
            info = comments_map.get(cid)
            if info is None:
                continue
            block_comments.append(Comment(
                comment_id=cid,
                author=info['author'],
                date=info['date'],
                text=info['text'],
                anchor_text=text[s:e],
                anchor_range=(s, e),
            ))
```

注意：之前 `_paragraph_accepted_text_and_revisions` 返回的是 `_comments_raw`（被 `_` 忽略了），需要改变量名：把 `text, revisions, _comments_raw = ...` 显式用于赋值；然后把 `block_comments` 传给构造 `ParagraphBlock/HeadingBlock/ListBlock items 情形下的 item 不挂 comments`，表格单元格里的 comment 暂不处理。

对 paragraph / heading 情形，把 `comments=block_comments` 传入。对 list，合并的每个 item 没有单独挂 comments（spec §6.3 以 anchor 所在 Block 为粒度；若 list 里有 comment，归到 List 作为整块）。修改：

```python
        if hlevel is not None:
            _flush_list(); _flush_code()
            blocks.append(HeadingBlock(level=hlevel, text=text, raw=text,
                                       revisions=revisions,
                                       comments=block_comments))
            continue

        if nid is not None:
            _flush_code()
            ordered = (nid == 2)
            if list_buf_ordered is None:
                list_buf_ordered = ordered
            if list_buf_ordered != ordered:
                _flush_list()
                list_buf_ordered = ordered
            # 若 list item 带 comment，把 comment 挤到 list_buf_pending_comments
            list_buf_items.append(text)
            # 保留：list 级 comments 由上层（docx_to_md）在 classify 阶段处理
            # 为简化暂放弃，稍后 Task 22 做分流
            continue

        if is_code:
            _flush_list()
            code_buf_lines.append(text)
            continue

        _flush_list(); _flush_code()
        if not text.strip():
            blocks.append(BlankBlock(raw=''))
        else:
            blocks.append(ParagraphBlock(text=text, raw=text,
                                         revisions=revisions,
                                         comments=block_comments))
```

- [ ] **Step 5: 跑测试通过**

Run: `python3.14 -m pytest tests/test_docx_reader.py -v`
Expected: 17 passed。

- [ ] **Step 6: commit**

```bash
git add docx_reader.py tests/
git commit -m "$(cat <<'EOF'
feat(docx_reader): 解析 word/comments.xml + commentRangeStart/End 锚点

段落内 commentRangeStart/End 的字符偏移拼出 anchor_range；
无 range 的孤立 commentReference 用同点坐标表示。批注挂到所在 Block.comments。
list / table 里的 comment 留到 docx_to_md 阶段另行处理。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Stage D — `comment_classifier.py`

### Task 15: `classify()` — Sonnet 4.6 批注分类

**Files:**
- Create: `comment_classifier.py`
- Create: `tests/test_comment_classifier.py`

**关键点：** Anthropic 客户端必须**依赖注入**（`client: Anthropic`），以便测试 mock。模块不在导入时创建 client，也不在 classify() 里隐式 `os.getenv('ANTHROPIC_API_KEY')`—传入 `client=None` 代表降级。

- [ ] **Step 1: 写失败测试**

Create `tests/test_comment_classifier.py`:
```python
"""comment_classifier.py 的测试。Anthropic 客户端 100% mock。"""
import json
from unittest.mock import MagicMock

import pytest

from comment_classifier import classify, ClassifierError


class _FakeAnthropic:
    """模拟 client.messages.create(...) 的最小 shape。"""
    def __init__(self, response_text: str, should_raise: bool = False):
        self._text = response_text
        self._raise = should_raise
        self.messages = MagicMock()
        self.messages.create = self._create

    def _create(self, **kwargs):
        if self._raise:
            raise RuntimeError('API boom')
        m = MagicMock()
        # Anthropic SDK 的 Message.content[0].text
        m.content = [MagicMock(text=self._text, type='text')]
        return m


def _ctx():
    return dict(
        block_text='前者发生在预训练阶段。',
        anchor_text='发生在',
        comment_body='改成：出现于',
        md_context='上下文内容',
    )


# ── edit case ──────────────────────────────────────────────
def test_classify_edit_high_confidence():
    client = _FakeAnthropic(json.dumps({
        'kind': 'edit',
        'new_text': '前者出现于预训练阶段。',
        'confidence': 0.92,
        'reasoning': '祈使型明确指令',
    }))
    result = classify(client=client, **_ctx())
    assert result['kind'] == 'edit'
    assert result['new_text'] == '前者出现于预训练阶段。'
    assert result['confidence'] == 0.92


# ── opinion case ───────────────────────────────────────────
def test_classify_opinion():
    client = _FakeAnthropic(json.dumps({
        'kind': 'opinion',
        'new_text': None,
        'confidence': 0.8,
        'reasoning': '未给出替换文本',
    }))
    r = classify(client=client, **_ctx())
    assert r['kind'] == 'opinion'
    assert r['new_text'] is None


# ── 降级路径 ──────────────────────────────────────────────
def test_classify_no_client_returns_opinion():
    r = classify(client=None, **_ctx())
    assert r['kind'] == 'opinion'
    assert r['confidence'] == 0.0
    assert 'degraded' in r['reasoning']


def test_classify_api_exception_returns_opinion():
    client = _FakeAnthropic('', should_raise=True)
    r = classify(client=client, **_ctx())
    assert r['kind'] == 'opinion'
    assert r['confidence'] == 0.0
    assert 'API error' in r['reasoning']


def test_classify_malformed_json_returns_opinion():
    client = _FakeAnthropic('not a json{')
    r = classify(client=client, **_ctx())
    assert r['kind'] == 'opinion'
    assert r['confidence'] == 0.0
    assert 'parse' in r['reasoning'].lower()


def test_classify_schema_missing_fields_returns_opinion():
    client = _FakeAnthropic(json.dumps({'kind': 'edit'}))  # 缺 confidence/new_text
    r = classify(client=client, **_ctx())
    assert r['kind'] == 'opinion'
    assert 'schema' in r['reasoning'].lower()


def test_classify_kwarg_shape_invokes_cache_control():
    """验证调用 API 时带了 cache_control=ephemeral（用 MagicMock.call_args 检查）。"""
    client = _FakeAnthropic(json.dumps({
        'kind': 'opinion', 'new_text': None, 'confidence': 0.5, 'reasoning': '-',
    }))
    classify(client=client, **_ctx())
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs['model'] == 'claude-sonnet-4-6'
    sys_list = kwargs['system']
    assert isinstance(sys_list, list)
    assert sys_list[0]['cache_control'] == {'type': 'ephemeral'}
```

- [ ] **Step 2: 跑失败测试**

Run: `python3.14 -m pytest tests/test_comment_classifier.py -v`
Expected: 7 ERROR（`ModuleNotFoundError`）。

- [ ] **Step 3: 实现 `comment_classifier.py`**

```python
"""comment_classifier.py — 用 Claude Sonnet 4.6 判断 Word 批注是
『明确修改指令』还是『意见/建议』。

设计约束：
  - 客户端依赖注入，方便测试 mock；client=None 直接降级为 opinion
  - 任何异常 / 解析失败 / schema 不全 都降级为 opinion（不抛出到调用方）
  - SYSTEM 用 prompt caching（ephemeral）摊低后续批注的成本
"""
import json
from typing import Optional


MODEL = 'claude-sonnet-4-6'
MAX_TOKENS = 500


SYSTEM_PROMPT = """\
你是中文技术书籍审校的辅助分类器。给定一条 Word 批注，判断它是"明确的文本修改指令"
还是"意见/建议"。

判别规则：
- edit：批注使用祈使/命令式或直接给出替换文本（"改成 X"、"X→Y"、"删掉"、
  "这句应为: ..."）
- opinion：批注在提问、讨论、建议但未给出确定的替换文本

边界判定：信息不足以确定替换文本时，返回 kind='opinion'。绝不自行发明替换文本。

输出必须是单个 JSON 对象，严格遵循：
{
  "kind": "edit" | "opinion",
  "new_text": string | null,
  "confidence": number,
  "reasoning": string
}
不要包装在 markdown code fence；不要有其他输出。
"""


USER_TEMPLATE = """\
批注锚点选中原文：
{anchor_text}

批注正文：
{comment_body}

锚点所在段落：
{block_text}

上下文：
{md_context}
"""


class ClassifierError(RuntimeError):
    """供外部显式捕获（实际上 classify 不抛出）。"""


def _degraded(reason: str) -> dict:
    return {
        'kind': 'opinion',
        'new_text': None,
        'confidence': 0.0,
        'reasoning': reason,
    }


def classify(*, client,
             block_text: str,
             anchor_text: str,
             comment_body: str,
             md_context: str) -> dict:
    """Classify a Word comment. 失败总是降级为 opinion。

    返回 dict：
      {'kind': 'edit' | 'opinion',
       'new_text': str | None,
       'confidence': float,
       'reasoning': str}
    """
    if client is None:
        return _degraded('degraded: no ANTHROPIC client provided')

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[{
                'type': 'text',
                'text': SYSTEM_PROMPT,
                'cache_control': {'type': 'ephemeral'},
            }],
            messages=[{
                'role': 'user',
                'content': USER_TEMPLATE.format(
                    anchor_text=anchor_text,
                    comment_body=comment_body,
                    block_text=block_text,
                    md_context=md_context,
                ),
            }],
        )
    except Exception as e:
        return _degraded(f'API error: {e}')

    # 取首个 text block
    try:
        text_raw = ''
        for blk in resp.content:
            blk_type = getattr(blk, 'type', 'text')
            if blk_type == 'text':
                text_raw += getattr(blk, 'text', '')
        text_raw = text_raw.strip()
    except Exception as e:
        return _degraded(f'unexpected response shape: {e}')

    try:
        data = json.loads(text_raw)
    except json.JSONDecodeError as e:
        return _degraded(f'could not parse JSON: {e}')

    # schema check
    required = {'kind', 'new_text', 'confidence', 'reasoning'}
    if not isinstance(data, dict) or not required.issubset(data.keys()):
        return _degraded(f'schema missing fields: {sorted(required - set(data.keys() if isinstance(data, dict) else []))}')

    if data['kind'] not in ('edit', 'opinion'):
        return _degraded('schema: kind not in {edit, opinion}')

    try:
        conf = float(data['confidence'])
    except (TypeError, ValueError):
        return _degraded('schema: confidence not a number')

    return {
        'kind': data['kind'],
        'new_text': data['new_text'],
        'confidence': conf,
        'reasoning': str(data['reasoning']),
    }
```

- [ ] **Step 4: 跑测试通过**

Run: `python3.14 -m pytest tests/test_comment_classifier.py -v`
Expected: 7 passed。

- [ ] **Step 5: commit**

```bash
git add comment_classifier.py tests/test_comment_classifier.py
git commit -m "$(cat <<'EOF'
feat(comment_classifier): Sonnet 4.6 + prompt caching 批注分类

依赖注入 Anthropic 客户端；SYSTEM 带 cache_control=ephemeral。
任何异常 / JSON 解析失败 / schema 不全 / 无 client 都降级为 opinion（不抛给上层）。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Stage E — `docx_to_md.py` 回灌核心

**模块职责：** 接收 baseline blocks（由 `git show <base_sha>:<path>.md` 再经 `md_core.parse_md_blocks`）与 reviewed blocks（由 `docx_reader.read_docx`），产出 `List[MdEdit]` 并应用到 baseline md 文本，返回新 md 内容与 commit message。

**关键数据结构（已在 spec §5.3，此处定型）：**
```python
@dataclass
class BlockMatch:
    base_block: Optional[Block]
    reviewed_block: Optional[Block]
    kind: Literal['equal', 'text_edit', 'struct_change', 'insert', 'delete']

@dataclass
class MdEdit:
    target_line_range: Tuple[int, int]   # baseline md 行号 [start, end)
    replacement: str                     # 空串 = 删除（整块含尾换行）
    reason: str
    provenance: str
```

**目录：** 所有新增测试放 `tests/test_docx_to_md.py`。

---

### Task 16: BlockMatch / MdEdit dataclass + 两轮块匹配

**Files:**
- Create: `docx_to_md.py`
- Create: `tests/test_docx_to_md.py`

- [ ] **Step 1: 写失败测试**

Create `tests/test_docx_to_md.py`:
```python
"""docx_to_md.py 块匹配与分级 MdEdit 生成测试。"""
from md_core import (
    ParagraphBlock, HeadingBlock, EquationBlock,
    TableBlock, CodeBlock, FigureBlock, ListBlock,
)
from docx_to_md import match_blocks, BlockMatch


def _p(t): return ParagraphBlock(text=t, raw=t)


def test_match_blocks_all_equal():
    base = [_p('A'), _p('B'), _p('C')]
    rev  = [_p('A'), _p('B'), _p('C')]
    matches = match_blocks(base, rev)
    assert len(matches) == 3
    assert all(m.kind == 'equal' for m in matches)


def test_match_blocks_text_edit_high_similarity():
    base = [_p('前者发生在预训练阶段。')]
    rev  = [_p('前者出现于预训练阶段。')]
    m = match_blocks(base, rev)
    assert len(m) == 1
    assert m[0].kind == 'text_edit'
    assert m[0].base_block.text == '前者发生在预训练阶段。'
    assert m[0].reviewed_block.text == '前者出现于预训练阶段。'


def test_match_blocks_low_similarity_becomes_delete_insert():
    base = [_p('完全不同的一段 A')]
    rev  = [_p('XYZ 另起的一段内容')]
    m = match_blocks(base, rev)
    # 粗匹配为 replace，ratio < 0.5 故拆成 delete + insert
    kinds = [x.kind for x in m]
    assert 'delete' in kinds and 'insert' in kinds


def test_match_blocks_pure_insert():
    base = [_p('A')]
    rev  = [_p('A'), _p('B')]
    m = match_blocks(base, rev)
    assert m[0].kind == 'equal'
    assert m[1].kind == 'insert' and m[1].reviewed_block.text == 'B'


def test_match_blocks_pure_delete():
    base = [_p('A'), _p('B')]
    rev  = [_p('A')]
    m = match_blocks(base, rev)
    assert m[0].kind == 'equal'
    assert m[1].kind == 'delete' and m[1].base_block.text == 'B'


def test_match_blocks_struct_change_heading_level():
    base = [HeadingBlock(level=2, text='同文本', raw='## 同文本')]
    rev  = [HeadingBlock(level=3, text='同文本', raw='### 同文本')]
    m = match_blocks(base, rev)
    # heading 级别变 但文本同 → text_edit（保 level 变化）
    assert len(m) == 1
    assert m[0].kind == 'text_edit'


def test_match_blocks_table_shape_changed():
    base = [TableBlock(header=['A', 'B'], rows=[['1', '2']], caption='', raw='')]
    rev  = [TableBlock(header=['A', 'B', 'C'], rows=[['1', '2', '3']], caption='', raw='')]
    m = match_blocks(base, rev)
    assert len(m) == 1
    assert m[0].kind == 'struct_change'
```

- [ ] **Step 2: 跑失败测试**

Run: `python3.14 -m pytest tests/test_docx_to_md.py -v`
Expected: 7 ERROR（`ModuleNotFoundError`）。

- [ ] **Step 3: 实现 `docx_to_md.py` 的骨架 + `match_blocks()`**

```python
"""docx_to_md.py — 基线 Block vs 审校 Block 的分级比较、MdEdit 生成、应用。

核心入口：
  - match_blocks(base, rev) -> List[BlockMatch]
  - make_edits(base, rev, rev_blocks_full, base_md_text, ...) -> List[MdEdit]
  - apply_edits_to_md(baseline_text, edits) -> (new_text, warnings)
  - render_commit_message(edits, warnings, ...) -> str
"""
import difflib
import re
import os
import hashlib
from dataclasses import dataclass, field
from typing import List, Literal, Optional, Tuple

from md_core import (
    Block, BlankBlock,
    HeadingBlock, ParagraphBlock, EquationBlock,
    TableBlock, CodeBlock, FigureBlock, ListBlock,
)
from md_diff_docx import _block_key


# ──────────────────────────────────────────────────────────
# 数据类
# ──────────────────────────────────────────────────────────

@dataclass
class BlockMatch:
    base_block: Optional[Block]
    reviewed_block: Optional[Block]
    kind: Literal['equal', 'text_edit', 'struct_change', 'insert', 'delete']


@dataclass
class MdEdit:
    target_line_range: Tuple[int, int]
    replacement: str
    reason: str
    provenance: str = ''


# ──────────────────────────────────────────────────────────
# 块相似度与结构判断
# ──────────────────────────────────────────────────────────

def _ratio(a: Block, b: Block) -> float:
    return difflib.SequenceMatcher(None, _block_key(a), _block_key(b),
                                   autojunk=False).ratio()


def _is_struct_change(a: Block, b: Block) -> bool:
    if isinstance(a, TableBlock) and isinstance(b, TableBlock):
        # 形状：列数或行数不同
        if len(a.header) != len(b.header):
            return True
        if len(a.rows) != len(b.rows):
            return True
        return False
    if isinstance(a, ListBlock) and isinstance(b, ListBlock):
        if a.ordered != b.ordered:
            return True
        if len(a.items) != len(b.items):
            return True
        return False
    return False


# ──────────────────────────────────────────────────────────
# match_blocks
# ──────────────────────────────────────────────────────────

def match_blocks(base: List[Block], rev: List[Block]) -> List[BlockMatch]:
    """两轮块匹配。
    第一轮：SequenceMatcher on _block_key → equal/delete/insert/replace opcodes
    第二轮：对 replace 段里每对块做 ratio；
             ratio >= 0.5 → text_edit 或 struct_change
             ratio <  0.5 → 拆成 delete + insert
    （长度不相等的 replace 段按顺序 zip，多余的单独 delete / insert。）
    """
    base_f = [b for b in base if not isinstance(b, BlankBlock)]
    rev_f  = [b for b in rev  if not isinstance(b, BlankBlock)]
    keys_a = [_block_key(b) for b in base_f]
    keys_b = [_block_key(b) for b in rev_f]

    sm = difflib.SequenceMatcher(None, keys_a, keys_b, autojunk=False)
    matches: List[BlockMatch] = []

    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            for a, b in zip(base_f[i1:i2], rev_f[j1:j2]):
                matches.append(BlockMatch(a, b, 'equal'))
        elif op == 'delete':
            for a in base_f[i1:i2]:
                matches.append(BlockMatch(a, None, 'delete'))
        elif op == 'insert':
            for b in rev_f[j1:j2]:
                matches.append(BlockMatch(None, b, 'insert'))
        elif op == 'replace':
            a_chunk = base_f[i1:i2]
            b_chunk = rev_f[j1:j2]
            # 按顺序配对
            pairs = min(len(a_chunk), len(b_chunk))
            for k in range(pairs):
                a, b = a_chunk[k], b_chunk[k]
                r = _ratio(a, b)
                if r >= 0.5:
                    if _is_struct_change(a, b):
                        matches.append(BlockMatch(a, b, 'struct_change'))
                    else:
                        matches.append(BlockMatch(a, b, 'text_edit'))
                else:
                    matches.append(BlockMatch(a, None, 'delete'))
                    matches.append(BlockMatch(None, b, 'insert'))
            for a in a_chunk[pairs:]:
                matches.append(BlockMatch(a, None, 'delete'))
            for b in b_chunk[pairs:]:
                matches.append(BlockMatch(None, b, 'insert'))

    return matches
```

- [ ] **Step 4: 跑测试通过**

Run: `python3.14 -m pytest tests/test_docx_to_md.py -v`
Expected: 7 passed。

- [ ] **Step 5: commit**

```bash
git add docx_to_md.py tests/test_docx_to_md.py
git commit -m "$(cat <<'EOF'
feat(docx_to_md): BlockMatch / MdEdit + 两轮块匹配

用 md_diff_docx._block_key 做一轮 SequenceMatcher 粗匹配；replace 块按
SequenceMatcher.ratio 细分：≥0.5 记 text_edit / struct_change，否则拆成
delete + insert。为 TableBlock / ListBlock 先判 struct_change（列/行/长度变化）。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 17: paragraph / heading 的 MdEdit 生成

**Files:**
- Modify: `docx_to_md.py`
- Modify: `tests/test_docx_to_md.py`

**关键：** `make_edits()` 需要根据 baseline md 原文本定位每个 Block 的行号。采用简化策略——基线 block 解析时记录其在 md 里的起止行，用 `parse_md_blocks_with_spans(md_text)` 包装 `md_core.parse_md_blocks`。

- [ ] **Step 1: 追加辅助：`parse_md_blocks_with_spans()`**

在 `docx_to_md.py` 末尾追加：
```python
# ──────────────────────────────────────────────────────────
# 行号定位 — 重跑 md_core.tokenize 并记录每个 Block 的行号
# ──────────────────────────────────────────────────────────

from md_core import parse_md_blocks


def parse_md_blocks_with_spans(md_text: str):
    """返回 [(Block, start_line, end_line)]，行号是 0-indexed 半开区间。

    实现：
      - 拿到 Block 列表
      - 每个 Block.raw 在原文里按行匹配定位起点；
        end = start + raw.count('\\n') + 1
      - 由于 raw 已由 tokenize 记录原始 block 文本，匹配从上一个块的 end 开始推进即可
    """
    blocks = parse_md_blocks(md_text)
    lines = md_text.splitlines(keepends=True)
    result = []
    cursor = 0
    for b in blocks:
        raw = b.raw if hasattr(b, 'raw') else ''
        if isinstance(b, BlankBlock):
            # 空行占一行
            start = cursor
            end = cursor + 1
            cursor = end
            result.append((b, start, end))
            continue

        raw_lines = (raw.split('\n') if raw else [''])
        n = len(raw_lines)
        # 期望从 cursor 起就是该 block
        # 若 cursor 处不匹配（罕见，例如 tokenize 跳过了空行），向前扫描 3 行容差
        matched_start = None
        limit = min(cursor + 4, len(lines))
        for k in range(cursor, limit):
            slice_join = ''.join(l.rstrip('\n') for l in lines[k:k + n])
            expected = '\n'.join(raw_lines).rstrip('\n')
            if slice_join == expected or slice_join == expected + '':
                matched_start = k
                break
        if matched_start is None:
            # 宽松兜底：强行按 cursor 起算
            matched_start = cursor
        start = matched_start
        end = start + n
        cursor = end
        result.append((b, start, end))
    return result
```

- [ ] **Step 2: 写失败测试（paragraph / heading 分级）**

在 `tests/test_docx_to_md.py` 末尾追加：
```python
from docx_to_md import make_edits


def test_make_edits_paragraph_text_edit():
    base_md = '这是第一段。\n\n这是第二段。\n'
    rev_blocks = [
        ParagraphBlock(text='这是第一段。', raw='这是第一段。'),
        ParagraphBlock(text='这是改过的第二段。', raw='这是改过的第二段。'),
    ]
    edits = make_edits(base_md, rev_blocks)
    # 只有一条 text_edit
    assert len(edits) == 1
    e = edits[0]
    assert e.reason == 'text_edit'
    assert '改过的第二段' in e.replacement
    # 第二段在 base_md 里的行号
    assert e.target_line_range == (2, 3)


def test_make_edits_heading_text_edit_preserves_level():
    base_md = '## 旧标题\n\n正文\n'
    rev_blocks = [
        HeadingBlock(level=2, text='新标题', raw='新标题'),
        ParagraphBlock(text='正文', raw='正文'),
    ]
    edits = make_edits(base_md, rev_blocks)
    assert len(edits) == 1
    assert edits[0].reason == 'text_edit'
    assert edits[0].replacement == '## 新标题'


def test_make_edits_heading_level_change():
    base_md = '## 同文本\n'
    rev_blocks = [HeadingBlock(level=3, text='同文本', raw='同文本')]
    edits = make_edits(base_md, rev_blocks)
    assert len(edits) == 1
    # 级别改到 ### 同文本
    assert edits[0].replacement == '### 同文本'


def test_make_edits_equal_produces_no_edits():
    base_md = '第一段。\n\n第二段。\n'
    rev_blocks = [
        ParagraphBlock(text='第一段。', raw='第一段。'),
        ParagraphBlock(text='第二段。', raw='第二段。'),
    ]
    assert make_edits(base_md, rev_blocks) == []


def test_make_edits_insert_inserts_after_preceding_equal():
    base_md = '段一。\n\n段二。\n'
    rev_blocks = [
        ParagraphBlock(text='段一。', raw='段一。'),
        ParagraphBlock(text='新插入段。', raw='新插入段。'),
        ParagraphBlock(text='段二。', raw='段二。'),
    ]
    edits = make_edits(base_md, rev_blocks)
    assert len(edits) == 1
    e = edits[0]
    assert e.reason == 'insert'
    # 插在"段一。"后（位置索引 1 之后，且保持 blank 行）
    assert e.target_line_range[0] == 1
    assert e.target_line_range[1] == 1  # 插入不删除
    assert '新插入段。' in e.replacement


def test_make_edits_delete_removes_block_lines():
    base_md = '段一。\n\n要删。\n\n段二。\n'
    rev_blocks = [
        ParagraphBlock(text='段一。', raw='段一。'),
        ParagraphBlock(text='段二。', raw='段二。'),
    ]
    edits = make_edits(base_md, rev_blocks)
    assert len(edits) == 1
    e = edits[0]
    assert e.reason == 'delete'
    assert e.replacement == ''
    assert e.target_line_range == (2, 3)  # "要删。"一行
```

- [ ] **Step 3: 跑失败测试**

Run: `python3.14 -m pytest tests/test_docx_to_md.py -v -k "make_edits"`
Expected: 6 ERROR（`make_edits` 未定义）。

- [ ] **Step 4: 实现 `make_edits()` 第一版（仅 paragraph/heading；其他类型 Task 18-22 补）**

在 `docx_to_md.py` 末尾追加：
```python
# ──────────────────────────────────────────────────────────
# make_edits — 对每类 Block 产生 MdEdit
# ──────────────────────────────────────────────────────────

def _render_block_md(block: Block) -> str:
    """把一个 Block 渲染回单块 md 源码（不含末尾换行）。"""
    if isinstance(block, HeadingBlock):
        return '#' * block.level + ' ' + block.text
    if isinstance(block, ParagraphBlock):
        return block.text
    if isinstance(block, EquationBlock):
        latex = block.latex
        if latex.startswith('@omml:'):
            # 无可逆 LaTeX；后续 Task 21 会改为占位
            return f'<!-- REVIEW: formula content see attachments -->'
        return f'$${latex}$$'
    if isinstance(block, CodeBlock):
        return f'```{block.language}\n{block.code.rstrip()}\n```'
    if isinstance(block, ListBlock):
        if block.ordered:
            return '\n'.join(f'{i+1}. {it}' for i, it in enumerate(block.items))
        return '\n'.join(f'- {it}' for it in block.items)
    if isinstance(block, TableBlock):
        head = '| ' + ' | '.join(block.header) + ' |'
        sep  = '|' + '|'.join(['---'] * len(block.header)) + '|'
        rows = '\n'.join('| ' + ' | '.join(r) + ' |' for r in block.rows)
        return '\n'.join([head, sep, rows]) if rows else '\n'.join([head, sep])
    if isinstance(block, FigureBlock):
        return f'![{block.alt}]({block.path})'
    return ''


def _find_insertion_line(matches_with_span: list, idx: int) -> int:
    """给 matches_with_span 里第 idx 条 insert，找到前一个 equal/text_edit 的 end_line 作为插入行。
    若没有，返回 0。
    matches_with_span[i] = (BlockMatch, base_span_or_None)
    """
    for j in range(idx - 1, -1, -1):
        m, span = matches_with_span[j]
        if m.kind in ('equal', 'text_edit') and span is not None:
            return span[1]  # base end_line
    return 0


def make_edits(baseline_md_text: str,
               reviewed_blocks: List[Block]) -> List[MdEdit]:
    baseline_with_spans = parse_md_blocks_with_spans(baseline_md_text)
    base_blocks = [b for (b, _, _) in baseline_with_spans
                   if not isinstance(b, BlankBlock)]
    base_spans = {id(b): (s, e) for (b, s, e) in baseline_with_spans
                  if not isinstance(b, BlankBlock)}

    rev_blocks = [b for b in reviewed_blocks if not isinstance(b, BlankBlock)]

    matches = match_blocks(base_blocks, rev_blocks)

    # 预计算每个 match 对应的 base span（insert 无 base）
    matches_with_span = []
    for m in matches:
        span = base_spans.get(id(m.base_block)) if m.base_block is not None else None
        matches_with_span.append((m, span))

    edits: List[MdEdit] = []
    for idx, (m, span) in enumerate(matches_with_span):
        if m.kind == 'equal':
            continue
        if m.kind == 'text_edit':
            if span is None:
                continue
            new_md = _render_block_md(m.reviewed_block)
            edits.append(MdEdit(
                target_line_range=span,
                replacement=new_md,
                reason='text_edit',
                provenance=f'paragraph edit at line {span[0] + 1}',
            ))
        elif m.kind == 'struct_change':
            # Task 19 处理 table；其他结构变化先整块替换
            if span is None:
                continue
            new_md = _render_block_md(m.reviewed_block)
            edits.append(MdEdit(
                target_line_range=span,
                replacement=new_md,
                reason='struct_change',
                provenance=f'struct change at line {span[0] + 1}',
            ))
        elif m.kind == 'delete':
            if span is None:
                continue
            edits.append(MdEdit(
                target_line_range=span,
                replacement='',
                reason='delete',
                provenance=f'block deleted at line {span[0] + 1}',
            ))
        elif m.kind == 'insert':
            insert_at = _find_insertion_line(matches_with_span, idx)
            new_md = _render_block_md(m.reviewed_block)
            edits.append(MdEdit(
                target_line_range=(insert_at, insert_at),
                replacement=new_md,
                reason='insert',
                provenance=f'block inserted before line {insert_at + 1}',
            ))
    return edits
```

- [ ] **Step 5: 跑测试通过**

Run: `python3.14 -m pytest tests/test_docx_to_md.py -v`
Expected: 13 passed。

- [ ] **Step 6: commit**

```bash
git add docx_to_md.py tests/test_docx_to_md.py
git commit -m "$(cat <<'EOF'
feat(docx_to_md): paragraph / heading MdEdit 生成

parse_md_blocks_with_spans 把 md_core.tokenize 输出对齐原文行号；
make_edits 按 BlockMatch 分流产出 text_edit / insert / delete / struct_change。
Heading 保留原级别前缀 # 渲染。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 18: list / code 的 MdEdit 生成

**Files:**
- Modify: `docx_to_md.py`
- Modify: `tests/test_docx_to_md.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_docx_to_md.py` 末尾追加：
```python
def test_make_edits_list_item_changed():
    base_md = '- 第一\n- 第二\n- 第三\n\n后文\n'
    rev_blocks = [
        ListBlock(items=['第一', '第二改', '第三'], ordered=False, raw=''),
        ParagraphBlock(text='后文', raw='后文'),
    ]
    edits = make_edits(base_md, rev_blocks)
    # 简化策略：list 整块替换
    list_edits = [e for e in edits if e.reason in ('text_edit', 'list_edit')]
    assert len(list_edits) == 1
    assert '第二改' in list_edits[0].replacement
    assert '第一' in list_edits[0].replacement
    assert '第三' in list_edits[0].replacement


def test_make_edits_ordered_list_changes_to_unordered():
    base_md = '1. A\n2. B\n'
    rev_blocks = [
        ListBlock(items=['A', 'B'], ordered=False, raw=''),
    ]
    edits = make_edits(base_md, rev_blocks)
    assert len(edits) == 1
    assert edits[0].reason in ('struct_change', 'text_edit')
    assert edits[0].replacement.startswith('- A')


def test_make_edits_code_changed():
    base_md = '```python\nprint(1)\n```\n'
    rev_blocks = [
        CodeBlock(code='print(2)', language='python', title='', raw=''),
    ]
    edits = make_edits(base_md, rev_blocks)
    assert len(edits) == 1
    assert edits[0].reason == 'code_edit'
    assert 'print(2)' in edits[0].replacement


def test_make_edits_code_language_preserved_from_baseline():
    """如果 reviewed code 没有 language（docx_reader 读不出），从基线继承。"""
    base_md = '```python\nprint(1)\n```\n'
    rev_blocks = [
        CodeBlock(code='print(2)', language='', title='', raw=''),
    ]
    edits = make_edits(base_md, rev_blocks)
    assert '```python' in edits[0].replacement
```

- [ ] **Step 2: 跑失败测试**

Run: `python3.14 -m pytest tests/test_docx_to_md.py -v -k "list or code"`
Expected: 列表测试 PASS（已被 Task 17 的通用 struct_change/text_edit 覆盖），但 code_edit reason 与 language 继承 FAIL。

- [ ] **Step 3: 修改 `make_edits` 为 code 单独分类 + language 继承**

在 `make_edits` 内处理 `text_edit` 分支前加：
```python
            # code 特化：reason 改名、language 从基线继承
            if (isinstance(m.base_block, CodeBlock)
                    and isinstance(m.reviewed_block, CodeBlock)
                    and not m.reviewed_block.language
                    and m.base_block.language):
                m.reviewed_block.language = m.base_block.language
            if isinstance(m.base_block, CodeBlock) and isinstance(m.reviewed_block, CodeBlock):
                new_md = _render_block_md(m.reviewed_block)
                edits.append(MdEdit(
                    target_line_range=span,
                    replacement=new_md,
                    reason='code_edit',
                    provenance=f'code block edit at line {span[0] + 1}',
                ))
                continue
```

把这段放在 `if m.kind == 'text_edit':` 之内的最前面（在 `new_md = _render_block_md(...)` 之前）。

- [ ] **Step 4: 跑测试通过**

Run: `python3.14 -m pytest tests/test_docx_to_md.py -v`
Expected: 17 passed。

- [ ] **Step 5: commit**

```bash
git add docx_to_md.py tests/test_docx_to_md.py
git commit -m "$(cat <<'EOF'
feat(docx_to_md): code 块特化 MdEdit — reason='code_edit' 且从基线继承 language

docx_reader 不保留 ``` 后的语言标识，回灌时从 baseline CodeBlock.language 继承，
避免把 python 代码误降级为无标记 fenced code。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 19: table 精确 cell diff

**Files:**
- Modify: `docx_to_md.py`
- Modify: `tests/test_docx_to_md.py`

**策略：** 同形状 table（列数/行数都相同）→ 逐 cell 比较，每个不同的 cell 生成一条 `cell_edit` 的 MdEdit（行号对应 baseline md 里这行表格所在行）。不同形状 → 整块替换（已在 Task 16 作为 `struct_change`）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_docx_to_md.py` 末尾追加：
```python
def test_make_edits_table_cell_changes_same_shape():
    base_md = (
        '| A | B | C |\n'
        '|---|---|---|\n'
        '| 1 | 2 | 3 |\n'
        '| 4 | 5 | 6 |\n'
    )
    rev_blocks = [
        TableBlock(header=['A', 'B', 'C'],
                   rows=[['1', 'X', '3'], ['4', '5', 'Y']],
                   caption='', raw=''),
    ]
    edits = make_edits(base_md, rev_blocks)
    # 两个 cell 改动 → 两条 cell_edit
    cell_edits = [e for e in edits if e.reason == 'cell_edit']
    assert len(cell_edits) == 2
    # 第一条改在基线第 3 行（0-index=2），replacement 覆盖整行
    first = [e for e in cell_edits if e.target_line_range == (2, 3)][0]
    assert first.replacement == '| 1 | X | 3 |'
    second = [e for e in cell_edits if e.target_line_range == (3, 4)][0]
    assert second.replacement == '| 4 | 5 | Y |'


def test_make_edits_table_struct_change_replaces_whole_block():
    base_md = (
        '| A | B |\n'
        '|---|---|\n'
        '| 1 | 2 |\n'
    )
    rev_blocks = [
        TableBlock(header=['A', 'B', 'C'],
                   rows=[['1', '2', '3']], caption='', raw=''),
    ]
    edits = make_edits(base_md, rev_blocks)
    assert len(edits) == 1
    assert edits[0].reason == 'struct_change'
    assert '| A | B | C |' in edits[0].replacement
```

- [ ] **Step 2: 跑失败测试**

Run: `python3.14 -m pytest tests/test_docx_to_md.py -v -k table`
Expected: 第一个 test FAIL（当前同形状走 text_edit，不是 cell_edit）。

- [ ] **Step 3: 在 `make_edits` 里特化 Table text_edit**

在处理 `text_edit` 分支的 code 特化之后，补 table 特化：
```python
            if isinstance(m.base_block, TableBlock) and isinstance(m.reviewed_block, TableBlock):
                bb, rb = m.base_block, m.reviewed_block
                # 形状一致才走 cell_edit；否则在 match_blocks 阶段应已标 struct_change
                if (len(bb.header) == len(rb.header)
                        and len(bb.rows) == len(rb.rows)):
                    # header 行号 = span.start；分隔行 = span.start + 1；
                    # 数据行 k = span.start + 2 + k
                    start = span[0]
                    diffs = 0
                    # header
                    if bb.header != rb.header:
                        new_line = '| ' + ' | '.join(rb.header) + ' |'
                        edits.append(MdEdit(
                            target_line_range=(start, start + 1),
                            replacement=new_line,
                            reason='cell_edit',
                            provenance=f'table header edit at line {start + 1}',
                        ))
                        diffs += 1
                    # 数据行
                    for k, (orow, nrow) in enumerate(zip(bb.rows, rb.rows)):
                        if orow != nrow:
                            line_no = start + 2 + k
                            new_line = '| ' + ' | '.join(nrow) + ' |'
                            edits.append(MdEdit(
                                target_line_range=(line_no, line_no + 1),
                                replacement=new_line,
                                reason='cell_edit',
                                provenance=f'table cell edit at line {line_no + 1}',
                            ))
                            diffs += 1
                    if diffs > 0:
                        continue
                    # 否则全等 — 不产出 edit
                    continue
                # 形状一致但依赖没走到这里；fallback 整块替换
```

- [ ] **Step 4: 跑测试通过**

Run: `python3.14 -m pytest tests/test_docx_to_md.py -v`
Expected: 19 passed。

- [ ] **Step 5: commit**

```bash
git add docx_to_md.py tests/test_docx_to_md.py
git commit -m "$(cat <<'EOF'
feat(docx_to_md): table 同形状时产出 cell_edit，不同形状整块替换

同形状逐 cell 比较，每个差异 cell 生成一条 MdEdit，target 行号对应
baseline md 里这行 markdown 表格的那一行，replacement 为完整新行（含首尾 |）。
不同形状由 match_blocks 已标 struct_change，走整块替换路径。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 20: figure — 新图 sha256 落盘 + 改 md path

**Files:**
- Modify: `docx_to_md.py`
- Modify: `tests/test_docx_to_md.py`

**策略：** reviewed FigureBlock 的 path 形如 `@media:<filename>:<sha>`。回灌时：
1. `make_edits()` 接收 `media_bundle: dict[sha -> bytes]`（调用方从 `docx_reader` bundle 抽）
2. 对每个 figure diff，如 sha 未在 baseline `typora-user-images/img-<sha8>.png` 存在，则把字节写到该路径
3. `replacement = f'![{alt}](./typora-user-images/img-<sha8>.png)'`（按项目约定）

- [ ] **Step 1: 写失败测试**

在 `tests/test_docx_to_md.py` 末尾追加：
```python
def test_make_edits_figure_replace_writes_new_file(tmp_path, monkeypatch):
    from docx_to_md import make_edits_with_media

    base_md = '![旧](./typora-user-images/old.png)\n\n正文。\n'

    new_bytes = b'fake png bytes v2'
    new_sha = hashlib.sha256(new_bytes).hexdigest()
    short = new_sha[:8]

    rev_blocks = [
        FigureBlock(alt='新', path=f'@media:image7.png:{new_sha}',
                    caption='', raw=''),
        ParagraphBlock(text='正文。', raw='正文。'),
    ]
    media = {new_sha: new_bytes}

    # 运行在 tmp_path 下
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'typora-user-images').mkdir()

    edits = make_edits_with_media(base_md, rev_blocks, media)

    figure_edits = [e for e in edits if e.reason == 'figure_replaced']
    assert len(figure_edits) == 1
    e = figure_edits[0]
    assert e.target_line_range == (0, 1)
    assert f'typora-user-images/img-{short}.png' in e.replacement
    # 文件应已写入
    out_file = tmp_path / 'typora-user-images' / f'img-{short}.png'
    assert out_file.exists()
    assert out_file.read_bytes() == new_bytes


def test_make_edits_figure_same_sha_no_change(tmp_path, monkeypatch):
    from docx_to_md import make_edits_with_media
    base_md = '![alt](./typora-user-images/img-abc12345.png)\n'
    sha = 'a' * 64  # 假设这就是该 png 的 sha
    # reviewed 有相同 sha → 与基线匹配，match_blocks 生成 equal
    rev_blocks = [
        FigureBlock(alt='alt',
                    path=f'@media:image1.png:{sha}',
                    caption='', raw=''),
    ]
    # baseline FigureBlock 由 parse_md_blocks 解析出；它的 path 是相对路径字符串
    # 与 reviewed 的 @media:... 不同 → 触发 ratio；我们只验证：
    # 当 docx reviewed FigureBlock.path 中的 sha 的前 8 位与 baseline 路径里
    # 'img-<sha8>.png' 一致时，视为未改。

    monkeypatch.chdir(tmp_path)
    (tmp_path / 'typora-user-images').mkdir()
    edits = make_edits_with_media(base_md, rev_blocks, {sha: b'x'})
    # 期望不产出 figure_replaced
    assert not any(e.reason == 'figure_replaced' for e in edits)
```

- [ ] **Step 2: 跑失败测试**

Run: `python3.14 -m pytest tests/test_docx_to_md.py -v -k figure`
Expected: FAIL（`make_edits_with_media` 未定义）。

- [ ] **Step 3: 在 `docx_to_md.py` 实现 figure 特化与 `make_edits_with_media`**

新增辅助：
```python
# ──────────────────────────────────────────────────────────
# Figure 处理
# ──────────────────────────────────────────────────────────

_FIGURE_FILENAME_RE = re.compile(r'img-([0-9a-f]{8,})\.png$', re.IGNORECASE)


def _figure_sha_from_reviewed(fb: FigureBlock) -> Optional[str]:
    """从 reviewed FigureBlock.path = '@media:<filename>:<sha>' 拿出 sha。"""
    if not fb.path.startswith('@media:'):
        return None
    parts = fb.path.split(':')
    if len(parts) != 3:
        return None
    return parts[2]


def _figure_sha_short_from_baseline(fb: FigureBlock) -> Optional[str]:
    """从 baseline 路径里 img-<sha8>.png 拿 8 位 sha。"""
    m = _FIGURE_FILENAME_RE.search(fb.path or '')
    return m.group(1) if m else None


def _maybe_persist_figure(sha: str, bytes_data: bytes,
                          image_dir: str = 'typora-user-images') -> str:
    """若 img-<sha8>.png 不存在则写入；返回相对路径（带 ./）。"""
    os.makedirs(image_dir, exist_ok=True)
    fn = f'img-{sha[:8]}.png'
    out_path = os.path.join(image_dir, fn)
    if not os.path.exists(out_path):
        with open(out_path, 'wb') as f:
            f.write(bytes_data)
    return f'./{image_dir}/{fn}'


def make_edits_with_media(baseline_md_text: str,
                          reviewed_blocks: List[Block],
                          media: dict) -> List[MdEdit]:
    """make_edits 的扩展：接收 media dict {sha -> bytes}，
    在 FigureBlock text_edit 时落盘新图并改 md path。"""
    edits = make_edits(baseline_md_text, reviewed_blocks)

    # 后处理：把 make_edits 产出的图片 text_edit / struct_change 特化
    # 重新按 matches 检查 figure 对
    baseline_with_spans = parse_md_blocks_with_spans(baseline_md_text)
    base_blocks = [b for (b, _, _) in baseline_with_spans
                   if not isinstance(b, BlankBlock)]
    base_spans = {id(b): (s, e) for (b, s, e) in baseline_with_spans
                  if not isinstance(b, BlankBlock)}
    rev_blocks = [b for b in reviewed_blocks if not isinstance(b, BlankBlock)]
    matches = match_blocks(base_blocks, rev_blocks)

    # 构建 line_range -> edit 的索引以便覆盖
    edits_by_range = {(e.target_line_range, e.reason): e for e in edits}

    for m in matches:
        if m.kind not in ('text_edit', 'struct_change'):
            continue
        if not (isinstance(m.base_block, FigureBlock) and
                isinstance(m.reviewed_block, FigureBlock)):
            continue
        span = base_spans.get(id(m.base_block))
        if span is None:
            continue

        rev_sha = _figure_sha_from_reviewed(m.reviewed_block)
        base_sha_short = _figure_sha_short_from_baseline(m.base_block)

        # 前 8 位命中则视为同图：移除已有 edit（若有）
        if rev_sha and base_sha_short and rev_sha[:8] == base_sha_short:
            # 同图；清除 text_edit（若有）
            for key in list(edits_by_range.keys()):
                if key[0] == span:
                    edits_by_range.pop(key, None)
            continue

        # 落盘 + 产出 figure_replaced
        bytes_data = media.get(rev_sha) if rev_sha else None
        if bytes_data is None:
            # 没图字节；用原路径
            new_path = m.reviewed_block.path if not m.reviewed_block.path.startswith('@media:') else ''
        else:
            new_path = _maybe_persist_figure(rev_sha, bytes_data)
        alt = m.reviewed_block.alt or m.base_block.alt
        new_md = f'![{alt}]({new_path})'

        # 替换该 span 上已有的 edit，reason 改为 figure_replaced
        for key in list(edits_by_range.keys()):
            if key[0] == span:
                edits_by_range.pop(key, None)
        edits_by_range[(span, 'figure_replaced')] = MdEdit(
            target_line_range=span,
            replacement=new_md,
            reason='figure_replaced',
            provenance=f'figure replace at line {span[0] + 1}, sha={rev_sha[:8] if rev_sha else "?"}',
        )

    return list(edits_by_range.values())
```

- [ ] **Step 4: 跑测试通过**

Run: `python3.14 -m pytest tests/test_docx_to_md.py -v`
Expected: 21 passed。

- [ ] **Step 5: commit**

```bash
git add docx_to_md.py tests/test_docx_to_md.py
git commit -m "$(cat <<'EOF'
feat(docx_to_md): figure replace — 新图按 sha256 落盘 typora-user-images/img-<sha8>.png

make_edits_with_media 接受 {sha -> bytes} 媒体字节。sha[:8] 等于基线
img-<sha8>.png 则视为未改；否则写入 typora-user-images/img-<sha8>.png
并产出 reason='figure_replaced' 的 MdEdit 覆盖原 text_edit。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 21: equation — 占位 + 片段 docx/截图

**Files:**
- Modify: `docx_to_md.py`
- Modify: `tests/test_docx_to_md.py`

**策略：**
- 公式被改（reviewed EquationBlock.latex = `@omml:<fp>` 与 baseline 不同）→ `replacement = '<!-- REVIEW: formula changed, see attachments/N.png -->'`
- 同时把 reviewed OMML 以最小骨架写成 `review/attachments/<N>.docx`；若系统有 `libreoffice`，调 `libreoffice --headless --convert-to png` 生成 `<N>.png`，无则保留 docx

- [ ] **Step 1: 写失败测试**

在 `tests/test_docx_to_md.py` 末尾追加：
```python
def test_make_edits_equation_changed_emits_placeholder(tmp_path, monkeypatch):
    from docx_to_md import make_edits_with_media

    base_md = '正文。\n\n$$a + b = c$$\n\n后文。\n'
    # reviewed：指纹不同
    rev_blocks = [
        ParagraphBlock(text='正文。', raw='正文。'),
        EquationBlock(latex='@omml:ffffffffffffffff' + 'f' * 48,
                      raw='<m:oMath/>'),
        ParagraphBlock(text='后文。', raw='后文。'),
    ]
    monkeypatch.chdir(tmp_path)
    edits = make_edits_with_media(base_md, rev_blocks, media={})

    eq_edits = [e for e in edits if e.reason == 'formula_changed']
    assert len(eq_edits) == 1
    e = eq_edits[0]
    assert '<!-- REVIEW: formula changed' in e.replacement
    # attachments 目录下应有片段 docx（不依赖 libreoffice）
    assert (tmp_path / 'review' / 'attachments').exists()
    docx_files = list((tmp_path / 'review' / 'attachments').glob('*.docx'))
    assert len(docx_files) == 1


def test_make_edits_equation_same_fingerprint_no_edit(tmp_path, monkeypatch):
    from docx_to_md import make_edits_with_media

    # baseline latex '@omml:abc' 只有在 docx_reader 读出来时才出现，
    # 但基线来自 md_core.parse_md_blocks 会产 latex='a + b = c' 而非 @omml:
    # 所以这个分支要在 "reviewed 块与 baseline 同 latex/omml" 时避免产 edit
    # 下面用 latex 互等
    base_md = '$$x=1$$\n'
    rev_blocks = [EquationBlock(latex='x=1', raw='')]
    monkeypatch.chdir(tmp_path)
    edits = make_edits_with_media(base_md, rev_blocks, media={})
    # match_blocks 按 _block_key='EQ:x=1' 对相等
    assert edits == []
```

- [ ] **Step 2: 跑失败测试**

Run: `python3.14 -m pytest tests/test_docx_to_md.py -v -k equation`
Expected: 第一个 FAIL（无 `formula_changed` reason 分支）；第二个可能直接 PASS（match_blocks 就返回 equal）。

- [ ] **Step 3: 在 `make_edits_with_media` 后追加 equation 特化**

在 `make_edits_with_media` 的 figure 循环之后追加：
```python
    # equation 特化
    attach_idx = 0
    for m in matches:
        if m.kind not in ('text_edit', 'struct_change'):
            continue
        if not (isinstance(m.base_block, EquationBlock) and
                isinstance(m.reviewed_block, EquationBlock)):
            continue
        span = base_spans.get(id(m.base_block))
        if span is None:
            continue
        # 若 reviewed latex 以 @omml: 开头表示未反转 LaTeX，视为"改过了"
        # 若两者 latex 都是可读 LaTeX 且相等，match_blocks 不会给 text_edit；
        # 所以到这里就代表公式变了
        attach_idx += 1
        _emit_formula_attachment(m.reviewed_block, attach_idx)
        new_md = (f'<!-- REVIEW: formula changed, '
                  f'see review/attachments/{attach_idx}.docx -->')
        for key in list(edits_by_range.keys()):
            if key[0] == span:
                edits_by_range.pop(key, None)
        edits_by_range[(span, 'formula_changed')] = MdEdit(
            target_line_range=span,
            replacement=new_md,
            reason='formula_changed',
            provenance=f'formula change at line {span[0] + 1}',
        )
```

新增 `_emit_formula_attachment`：
```python
import shutil as _shutil
import subprocess as _subprocess

def _emit_formula_attachment(eq: EquationBlock, idx: int) -> None:
    """把 reviewed EquationBlock.raw（OMML XML 片段）包成最小 docx，存到
    review/attachments/<idx>.docx。若系统有 libreoffice，再转成 <idx>.png。"""
    out_dir = os.path.join('review', 'attachments')
    os.makedirs(out_dir, exist_ok=True)
    docx_path = os.path.join(out_dir, f'{idx}.docx')

    W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    M = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
    body = (
        f'<w:p><m:oMathPara xmlns:m="{M}">{eq.raw}</m:oMathPara></w:p>'
        if eq.raw.startswith('<m:oMath') else
        f'<w:p><w:r><w:t xml:space="preserve">{eq.latex}</w:t></w:r></w:p>'
    )
    # 最小 docx 包（与 tests/fixtures/build_min_docx.py 同 spirit，避免相互依赖）
    import zipfile as _zf
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
          '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>')
    with _zf.ZipFile(docx_path, 'w', _zf.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', ct)
        z.writestr('_rels/.rels', rels)
        z.writestr('word/document.xml', doc)

    # 可选 libreoffice 转 png
    if _shutil.which('libreoffice') is not None:
        try:
            _subprocess.run(
                ['libreoffice', '--headless',
                 '--convert-to', 'png',
                 '--outdir', out_dir, docx_path],
                check=True, stdout=_subprocess.DEVNULL, stderr=_subprocess.PIPE,
                timeout=30,
            )
        except (_subprocess.CalledProcessError, _subprocess.TimeoutExpired):
            pass  # 保留 docx，下次用户可手工转
```

- [ ] **Step 4: 跑测试通过**

Run: `python3.14 -m pytest tests/test_docx_to_md.py -v`
Expected: 23 passed。

- [ ] **Step 5: commit**

```bash
git add docx_to_md.py tests/test_docx_to_md.py
git commit -m "$(cat <<'EOF'
feat(docx_to_md): formula change — 占位 + review/attachments/<N>.docx

OMML 指纹变化的公式在 md 中替换为 HTML 注释占位，并把 reviewed OMML 包成
最小骨架 docx 落盘 review/attachments/<idx>.docx；系统有 libreoffice 时额外
渲染为 <idx>.png，失败或缺省只保留 docx。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 22: comment → MdEdit 分流（经 classifier）

**Files:**
- Modify: `docx_to_md.py`
- Modify: `tests/test_docx_to_md.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_docx_to_md.py` 末尾追加：
```python
from unittest.mock import MagicMock
from md_core import Comment


def _mock_classifier_edit(new_text: str, conf: float):
    def fn(**kwargs):
        return {'kind': 'edit', 'new_text': new_text,
                'confidence': conf, 'reasoning': '-'}
    return fn


def _mock_classifier_opinion():
    def fn(**kwargs):
        return {'kind': 'opinion', 'new_text': None,
                'confidence': 0.5, 'reasoning': 'discussion'}
    return fn


def test_comment_edit_high_conf_becomes_text_edit(tmp_path, monkeypatch):
    from docx_to_md import make_edits_with_comments
    base_md = '前者发生在预训练阶段。\n'
    rev_block = ParagraphBlock(
        text='前者发生在预训练阶段。', raw='前者发生在预训练阶段。',
        comments=[Comment(comment_id=0, author='审校者',
                          date='2026-04-23T00:00:00Z',
                          text='改成：前者出现于预训练阶段。',
                          anchor_text='前者发生在预训练阶段。',
                          anchor_range=(0, 12))],
    )
    monkeypatch.chdir(tmp_path)
    edits = make_edits_with_comments(
        base_md, [rev_block],
        media={},
        classify_fn=_mock_classifier_edit('前者出现于预训练阶段。', 0.9),
    )
    ces = [e for e in edits if e.reason == 'comment_edit']
    assert len(ces) == 1
    assert ces[0].replacement == '前者出现于预训练阶段。'


def test_comment_edit_low_conf_becomes_opinion(tmp_path, monkeypatch):
    from docx_to_md import make_edits_with_comments
    base_md = '前者发生在预训练阶段。\n'
    rev_block = ParagraphBlock(
        text='前者发生在预训练阶段。', raw='前者发生在预训练阶段。',
        comments=[Comment(comment_id=0, author='审校者',
                          date='2026-04-23T00:00:00Z',
                          text='也许可以改一下？',
                          anchor_text='前者',
                          anchor_range=(0, 2))],
    )
    monkeypatch.chdir(tmp_path)
    edits = make_edits_with_comments(
        base_md, [rev_block], media={},
        classify_fn=_mock_classifier_edit('XXX', 0.5),  # conf < 0.7
    )
    cos = [e for e in edits if e.reason == 'comment_opinion']
    assert len(cos) == 1
    assert '<!-- REVIEWER[审校者]:' in cos[0].replacement


def test_comment_pure_opinion_becomes_opinion(tmp_path, monkeypatch):
    from docx_to_md import make_edits_with_comments
    base_md = '正文。\n'
    rev_block = ParagraphBlock(
        text='正文。', raw='正文。',
        comments=[Comment(comment_id=0, author='张三',
                          date='2026-04-23T00:00:00Z',
                          text='这段可以更精简',
                          anchor_text='正文。', anchor_range=(0, 3))],
    )
    monkeypatch.chdir(tmp_path)
    edits = make_edits_with_comments(
        base_md, [rev_block], media={},
        classify_fn=_mock_classifier_opinion(),
    )
    cos = [e for e in edits if e.reason == 'comment_opinion']
    assert len(cos) == 1
    assert '张三' in cos[0].replacement
```

- [ ] **Step 2: 跑失败测试**

Run: `python3.14 -m pytest tests/test_docx_to_md.py -v -k comment`
Expected: 3 ERROR（`make_edits_with_comments` 未定义）。

- [ ] **Step 3: 在 `docx_to_md.py` 实现 `make_edits_with_comments`**

```python
# ──────────────────────────────────────────────────────────
# Comment 分流
# ──────────────────────────────────────────────────────────

EDIT_CONFIDENCE_THRESHOLD = 0.7


def make_edits_with_comments(baseline_md_text: str,
                             reviewed_blocks: List[Block],
                             media: dict,
                             classify_fn) -> List[MdEdit]:
    """make_edits_with_media 的进一步扩展：把每个 reviewed Block.comments
    经 classify_fn 分流为 comment_edit 或 comment_opinion MdEdit。

    classify_fn 接受 block_text / anchor_text / comment_body / md_context
    四个关键字参数，返回 dict（同 comment_classifier.classify）。
    """
    edits = list(make_edits_with_media(baseline_md_text, reviewed_blocks, media))

    # 重建 baseline span 映射用于定位 comment 锚点的行号
    baseline_with_spans = parse_md_blocks_with_spans(baseline_md_text)
    # 匹配 reviewed block → baseline block（用于获取行号）
    base_blocks = [b for (b, _, _) in baseline_with_spans
                   if not isinstance(b, BlankBlock)]
    base_spans = {id(b): (s, e) for (b, s, e) in baseline_with_spans
                  if not isinstance(b, BlankBlock)}
    rev_blocks_f = [b for b in reviewed_blocks if not isinstance(b, BlankBlock)]
    matches = match_blocks(base_blocks, rev_blocks_f)

    # 构造 reviewed_block -> base_span 的映射
    rev_to_span = {}
    for m in matches:
        if m.reviewed_block is not None and m.base_block is not None:
            span = base_spans.get(id(m.base_block))
            if span is not None:
                rev_to_span[id(m.reviewed_block)] = span

    lines = baseline_md_text.splitlines()
    for rb in rev_blocks_f:
        for c in getattr(rb, 'comments', []):
            span = rev_to_span.get(id(rb))
            if span is None:
                # 纯新增块的 comment；跳过（罕见）
                continue
            anchor_line = span[0]
            # 上下文：baseline 前后各 1 段
            ctx_start = max(0, span[0] - 2)
            ctx_end = min(len(lines), span[1] + 2)
            md_context = '\n'.join(lines[ctx_start:ctx_end])

            result = classify_fn(
                block_text=getattr(rb, 'text', '') or getattr(rb, 'latex', '') or '',
                anchor_text=c.anchor_text,
                comment_body=c.text,
                md_context=md_context,
            )
            if (result.get('kind') == 'edit' and
                    result.get('confidence', 0) >= EDIT_CONFIDENCE_THRESHOLD and
                    result.get('new_text')):
                edits.append(MdEdit(
                    target_line_range=span,
                    replacement=result['new_text'],
                    reason='comment_edit',
                    provenance=(f'comment by {c.author} (conf={result["confidence"]:.2f}): '
                                f'"{c.text[:30]}"'),
                ))
            else:
                # 追加到锚点所在行之后
                note = f'\n<!-- REVIEWER[{c.author}]: {c.text} -->'
                edits.append(MdEdit(
                    target_line_range=(span[1], span[1]),
                    replacement=note,
                    reason='comment_opinion',
                    provenance=f'comment by {c.author}',
                ))
    return edits
```

- [ ] **Step 4: 跑测试通过**

Run: `python3.14 -m pytest tests/test_docx_to_md.py -v`
Expected: 26 passed。

- [ ] **Step 5: commit**

```bash
git add docx_to_md.py tests/test_docx_to_md.py
git commit -m "$(cat <<'EOF'
feat(docx_to_md): comment → MdEdit 经 classifier 分流

classify_fn 作为注入（comment_classifier.classify 的偏函数或 mock），
confidence >= 0.7 且 kind='edit' → comment_edit（替换锚点 Block）；
其他 → comment_opinion（在锚点块尾部插 <!-- REVIEWER[...]: ... --> 注释）。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 23: `apply_edits_to_md()` — 倒序应用 + 冲突检测

**Files:**
- Modify: `docx_to_md.py`
- Modify: `tests/test_docx_to_md.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_docx_to_md.py` 末尾追加：
```python
def test_apply_edits_replace_single_line():
    from docx_to_md import apply_edits_to_md
    base = 'A\nB\nC\n'
    edits = [MdEdit(target_line_range=(1, 2),
                    replacement='BB', reason='text_edit')]
    new_text, warnings = apply_edits_to_md(base, edits)
    assert new_text == 'A\nBB\nC\n'
    assert warnings == []


def test_apply_edits_multiple_in_order_descending():
    from docx_to_md import apply_edits_to_md
    base = 'A\nB\nC\nD\n'
    edits = [
        MdEdit(target_line_range=(0, 1), replacement='A1', reason='text_edit'),
        MdEdit(target_line_range=(3, 4), replacement='D1', reason='text_edit'),
    ]
    new_text, warnings = apply_edits_to_md(base, edits)
    assert new_text == 'A1\nB\nC\nD1\n'
    assert warnings == []


def test_apply_edits_delete():
    from docx_to_md import apply_edits_to_md
    base = 'A\nB\nC\n'
    edits = [MdEdit(target_line_range=(1, 2), replacement='', reason='delete')]
    new_text, _ = apply_edits_to_md(base, edits)
    assert new_text == 'A\nC\n'


def test_apply_edits_insert():
    from docx_to_md import apply_edits_to_md
    base = 'A\nB\n'
    edits = [MdEdit(target_line_range=(1, 1),
                    replacement='NEW', reason='insert')]
    new_text, _ = apply_edits_to_md(base, edits)
    assert new_text == 'A\nNEW\nB\n'


def test_apply_edits_conflict_warns_and_second_wins():
    from docx_to_md import apply_edits_to_md
    base = 'A\nB\nC\n'
    edits = [
        MdEdit(target_line_range=(1, 2), replacement='X',
               reason='text_edit', provenance='first'),
        MdEdit(target_line_range=(1, 2), replacement='Y',
               reason='text_edit', provenance='second'),
    ]
    new_text, warnings = apply_edits_to_md(base, edits)
    # 后者（second）覆盖前者
    assert new_text == 'A\nY\nC\n'
    assert len(warnings) == 1
    assert 'first' in warnings[0]


def test_apply_edits_opinion_appends_newline():
    from docx_to_md import apply_edits_to_md
    base = 'A\nB\n'
    edits = [MdEdit(target_line_range=(1, 1),
                    replacement='\n<!-- REVIEWER: x -->',
                    reason='comment_opinion')]
    new_text, _ = apply_edits_to_md(base, edits)
    assert new_text == 'A\n\n<!-- REVIEWER: x -->\nB\n'
```

- [ ] **Step 2: 跑失败测试**

Run: `python3.14 -m pytest tests/test_docx_to_md.py -v -k apply_edits`
Expected: 6 ERROR（`apply_edits_to_md` 未定义）。

- [ ] **Step 3: 实现 `apply_edits_to_md()`**

在 `docx_to_md.py` 末尾追加：
```python
# ──────────────────────────────────────────────────────────
# 应用 MdEdit 到基线 md 文本
# ──────────────────────────────────────────────────────────

def apply_edits_to_md(baseline_text: str,
                      edits: List[MdEdit]) -> Tuple[str, List[str]]:
    """按 target_line_range 逆序（[0] 从大到小）应用 edits。

    冲突：两条 range 完全相同 → 后者覆盖前者，前者被记入 warnings 列表。
    部分重叠（非相同）→ 同样后者覆盖，前者记 warning。
    返回 (new_text, warnings)。
    """
    warnings: List[str] = []
    if not edits:
        return baseline_text, warnings

    # 按 start 升序、end 升序稳定排序后，逆序处理
    sorted_edits = sorted(edits, key=lambda e: (e.target_line_range[0],
                                                e.target_line_range[1]))

    # 检测重叠
    effective: List[MdEdit] = []
    for e in sorted_edits:
        conflict = None
        for keep in effective:
            if _ranges_overlap(e.target_line_range, keep.target_line_range):
                conflict = keep
                break
        if conflict is not None:
            warnings.append(
                f'conflict: edit at {e.target_line_range} (reason={e.reason}, '
                f'provenance={e.provenance}) overlaps with earlier edit at '
                f'{conflict.target_line_range} '
                f'(reason={conflict.reason}, provenance={conflict.provenance}); '
                f'{conflict.provenance!r} dropped, '
                f'{e.provenance!r} kept'
            )
            effective.remove(conflict)
        effective.append(e)

    # 逆序应用
    effective.sort(key=lambda e: e.target_line_range[0], reverse=True)
    lines = baseline_text.splitlines(keepends=True)
    for e in effective:
        s, t = e.target_line_range
        if e.replacement == '':
            lines[s:t] = []
        else:
            lines[s:t] = [e.replacement + '\n']

    return ''.join(lines), warnings


def _ranges_overlap(a: Tuple[int, int], b: Tuple[int, int]) -> bool:
    """半开区间 [s, e) 是否重叠。相邻（插入在同一点）不算重叠。"""
    as_, ae = a
    bs_, be = b
    if as_ == ae and bs_ == be:
        # 两个都是点插入：同点视为重叠
        return as_ == bs_
    return as_ < be and bs_ < ae
```

- [ ] **Step 4: 跑测试通过**

Run: `python3.14 -m pytest tests/test_docx_to_md.py -v`
Expected: 32 passed。

- [ ] **Step 5: commit**

```bash
git add docx_to_md.py tests/test_docx_to_md.py
git commit -m "$(cat <<'EOF'
feat(docx_to_md): apply_edits_to_md 逆序应用 + 冲突检测

按 target_line_range 从大到小覆盖 lines 切片；半开区间重叠视为冲突，
后者胜出，被覆盖的 provenance 记入 warnings（上层会写进 commit message）。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 24: commit message 模板渲染

**Files:**
- Modify: `docx_to_md.py`
- Modify: `tests/test_docx_to_md.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_docx_to_md.py` 末尾追加：
```python
def test_render_commit_message_summary_counts():
    from docx_to_md import render_commit_message
    edits = [
        MdEdit(target_line_range=(0, 1), replacement='A', reason='text_edit',
               provenance='p1'),
        MdEdit(target_line_range=(3, 4), replacement='B', reason='text_edit',
               provenance='p2'),
        MdEdit(target_line_range=(5, 5),
               replacement='\n<!-- REVIEWER[x]: y -->',
               reason='comment_opinion', provenance='op'),
        MdEdit(target_line_range=(7, 8), replacement='', reason='delete',
               provenance='d'),
        MdEdit(target_line_range=(9, 10), replacement='C', reason='cell_edit',
               provenance='ce'),
    ]
    msg = render_commit_message(
        edits=edits, warnings=[],
        reviewer='张三', docx_filename='chapter_abc1234.docx',
        base_sha='abcdef1234567890' * 2 + 'abcd',
        baseline_source='metadata',
    )
    first_line = msg.splitlines()[0]
    assert '2 处文本修改' in first_line or '4 处文本修改' in first_line
    assert '1 条意见' in first_line
    assert 'chapter_abc1234.docx' in msg
    assert 'abcdef1' in msg  # short sha
    assert '基线来源: metadata' in msg
    assert 'Co-Authored-By: md-docx-bridge' in msg


def test_render_commit_message_with_warnings():
    from docx_to_md import render_commit_message
    msg = render_commit_message(
        edits=[MdEdit(target_line_range=(0, 1), replacement='x',
                      reason='text_edit', provenance='p')],
        warnings=['conflict: edit X overlaps Y'],
        reviewer='Z', docx_filename='a.docx',
        base_sha='a' * 40, baseline_source='cli',
    )
    assert 'WARNING' in msg or '警告' in msg
    assert 'conflict: edit X overlaps Y' in msg
```

- [ ] **Step 2: 跑失败测试**

Run: `python3.14 -m pytest tests/test_docx_to_md.py -v -k render_commit`
Expected: 2 ERROR。

- [ ] **Step 3: 实现 `render_commit_message()`**

在 `docx_to_md.py` 末尾追加：
```python
# ──────────────────────────────────────────────────────────
# commit message 模板
# ──────────────────────────────────────────────────────────

def _count_edits(edits: List[MdEdit]) -> dict:
    text_reasons = {'text_edit', 'comment_edit', 'cell_edit', 'code_edit',
                    'figure_replaced', 'formula_changed',
                    'insert', 'delete'}
    struct_reasons = {'struct_change', 'table_restructured'}
    c = {'text': 0, 'struct': 0, 'opinion': 0}
    for e in edits:
        if e.reason in text_reasons:
            c['text'] += 1
        elif e.reason in struct_reasons:
            c['struct'] += 1
        elif e.reason == 'comment_opinion':
            c['opinion'] += 1
    return c


def render_commit_message(*, edits: List[MdEdit],
                          warnings: List[str],
                          reviewer: str,
                          docx_filename: str,
                          base_sha: str,
                          baseline_source: str) -> str:
    cnt = _count_edits(edits)
    title = (f'review: {cnt["text"]} 处文本修改 / '
             f'{cnt["struct"]} 处结构改动 / '
             f'{cnt["opinion"]} 条意见')

    short = base_sha[:7]

    # 明细
    lines = []
    for e in edits:
        rng = f'第 {e.target_line_range[0] + 1}-{e.target_line_range[1]} 行' \
            if e.target_line_range[1] > e.target_line_range[0] \
            else f'第 {e.target_line_range[0] + 1} 行（插入）'
        lines.append(f'- {e.reason}: {rng}  {e.provenance}')

    body = [
        title,
        '',
        f'来自 {reviewer} 的审校（docx: {docx_filename}）',
        f'基线 commit: {short}',
        f'基线来源: {baseline_source}',
        '',
        '变动明细：',
    ] + (lines if lines else ['（无）'])

    if warnings:
        body.append('')
        body.append('WARNING / 警告：')
        for w in warnings:
            body.append(f'- {w}')

    body.append('')
    body.append('Co-Authored-By: md-docx-bridge <bridge@review.local>')
    return '\n'.join(body) + '\n'
```

- [ ] **Step 4: 跑测试通过**

Run: `python3.14 -m pytest tests/test_docx_to_md.py -v`
Expected: 34 passed。

- [ ] **Step 5: commit**

```bash
git add docx_to_md.py tests/test_docx_to_md.py
git commit -m "$(cat <<'EOF'
feat(docx_to_md): render_commit_message — 统计 + 明细 + 警告

按 reason 分类统计；明细行含 target_line_range / reason / provenance；
warnings 非空时追加 WARNING 段；末尾 Co-Authored-By md-docx-bridge。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Stage F — CLI 扩展

### Task 25: `cli.py export-review`

**Files:**
- Modify: `cli.py`
- Create: `tests/test_cli_review.py`

**数据流（与 spec §4.1 对齐）：**
1. `git_review.resolve_range(arg)` → `(base_sha, head_sha)`
2. `git_review.read_at(base_sha, path)` + `read_at(head_sha, path)` → 两版 md 文本
3. `md_core.parse_md_blocks(old)` / `parse_md_blocks(new)` → 两版 blocks
4. `md_diff_docx.DiffDocxRenderer.render_diff(old, new)` → docx（已有能力）
5. 输出路径：`<basename>_<head_sha7>.docx`
6. `git_review.stamp_docx_metadata(...)` + `update_review_state(...)`

- [ ] **Step 1: 写失败测试**

Create `tests/test_cli_review.py`:
```python
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
```

- [ ] **Step 2: 跑失败测试**

Run: `python3.14 -m pytest tests/test_cli_review.py -v`
Expected: 2 FAIL（cli.py 没有 `export-review` 子命令，会 `argparse error: invalid choice`）。

- [ ] **Step 3: 修改 `cli.py` 加 `export-review` 子命令**

在 `cli.py` 末尾的 `def main()` 之前新增：
```python
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
```

在 `main()` 里 subparsers 声明尾部追加：
```python
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
```

并在 dispatch 处追加：
```python
    elif args.command == 'export-review':
        cmd_export_review(args)
```

- [ ] **Step 4: 跑测试通过**

Run: `python3.14 -m pytest tests/test_cli_review.py -v -k export`
Expected: 2 passed。

- [ ] **Step 5: 回归 — 原有子命令不受影响**

Run: `python3.14 cli.py convert chapter3_new.md -o /tmp/chapter3_check3.docx`
Expected: 正常 413/413 成功输出。

- [ ] **Step 6: commit**

```bash
git add cli.py tests/test_cli_review.py
git commit -m "$(cat <<'EOF'
feat(cli): export-review 子命令 — md git commit → 送审 docx

调 git_review.resolve_range / read_at 取两版 md，经 md_diff_docx
渲染 Track Changes docx，写 custom.xml 溯源 + 更新 .review_state.json。
支持 <commit> / <base>..<head> / --since-last-review 三种范围。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 26: `cli.py import-review`

**Files:**
- Modify: `cli.py`
- Modify: `tests/test_cli_review.py`

**数据流（与 spec §4.2 对齐）：**
1. `git_review.resolve_baseline(docx, cli_base, cli_path)` → `(base_sha, path, source)`
2. `git_review.read_at(base_sha, path)` → baseline md text
3. `docx_reader.read_docx(reviewed_docx)` → reviewed blocks（+ 内部 media bundle）
4. `git_review.detect_reviewer(cli_reviewer, reviewed_docx)` → `(name, slug)`
5. 若有 `ANTHROPIC_API_KEY` 环境变量则构建 `anthropic.Anthropic()`；否则 classifier client=None
6. `docx_to_md.make_edits_with_comments(baseline, reviewed_blocks, media, classify_fn)` → edits
7. `docx_to_md.apply_edits_to_md(baseline, edits)` → new_md, warnings
8. `docx_to_md.render_commit_message(...)` → message
9. `git_review.commit_to_review_branch(...)` → (branch_ref, new_sha)
10. 打印成功

- [ ] **Step 1: 写失败测试**

在 `tests/test_cli_review.py` 末尾追加：
```python
def test_import_review_creates_branch_without_touching_head(tmp_git_repo):
    """用 export-review 产出的 docx 做 smoke：直接 import 应在 review 分支上
    得到一个 commit，HEAD 仍在 main。"""
    (tmp_git_repo / '.review_state.json').write_text(
        json.dumps({'last_exported_sha': None, 'last_exported_at': None, 'exports': []}),
        encoding='utf-8')
    _commit(tmp_git_repo, 'chapter.md', MIN_MD, 'v1')
    sha2 = _commit(tmp_git_repo, 'chapter.md', MIN_MD_V2, 'v2')

    # export
    r = _run_cli('export-review', sha2, '--path', 'chapter.md',
                 cwd=tmp_git_repo)
    assert r.returncode == 0, r.stderr
    docx = tmp_git_repo / f'chapter_{sha2[:7]}.docx'

    head_before = subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=tmp_git_repo, text=True).strip()

    # import（--reviewer 明确指定，避免走 LLM 分类；此 docx 无 comments）
    r = _run_cli('import-review', str(docx),
                 '--reviewer', '测试员',
                 cwd=tmp_git_repo)
    assert r.returncode == 0, r.stderr

    # HEAD 未变
    head_after = subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=tmp_git_repo, text=True).strip()
    assert head_before == head_after

    # review 分支存在（任意日期后缀）
    branches = subprocess.check_output(
        ['git', 'branch', '-a'], cwd=tmp_git_repo, text=True)
    assert 'review/ceshiyuan-' in branches


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
    """工作区脏 → 默认拒绝（exit 1）；--allow-dirty 仍应继续。"""
    (tmp_git_repo / '.review_state.json').write_text(
        json.dumps({'last_exported_sha': None, 'last_exported_at': None, 'exports': []}),
        encoding='utf-8')
    _commit(tmp_git_repo, 'chapter.md', MIN_MD, 'v1')
    sha2 = _commit(tmp_git_repo, 'chapter.md', MIN_MD_V2, 'v2')

    r = _run_cli('export-review', sha2, '--path', 'chapter.md', cwd=tmp_git_repo)
    assert r.returncode == 0, r.stderr
    docx = tmp_git_repo / f'chapter_{sha2[:7]}.docx'

    # 工作区加一个未提交改动
    (tmp_git_repo / 'dirty.txt').write_text('dirty', encoding='utf-8')

    # 默认拒绝
    r = _run_cli('import-review', str(docx), '--reviewer', '测试员',
                 cwd=tmp_git_repo)
    assert r.returncode != 0
    assert '工作区' in (r.stderr + r.stdout) or 'dirty' in (r.stderr + r.stdout).lower()
```

- [ ] **Step 2: 跑失败测试**

Run: `python3.14 -m pytest tests/test_cli_review.py -v -k import`
Expected: 2 FAIL（import-review 子命令不存在）。

- [ ] **Step 3: 修改 `cli.py` 加 `import-review`**

在 `cmd_export_review` 之后新增：
```python
def cmd_import_review(args):
    """回灌：审校 docx → review 分支 commit。"""
    import datetime
    import os as _os
    import subprocess as _sp
    from docx_reader import read_docx, DocxReaderError
    from docx_to_md import (
        make_edits_with_comments, apply_edits_to_md, render_commit_message,
    )
    from md_core import parse_md_blocks
    from git_review import (
        resolve_baseline, read_at, detect_reviewer, commit_to_review_branch,
        GitReviewError,
    )
    _ = parse_md_blocks  # reserved

    # 0. 工作区干净检查 — import-review 绝不在脏工作区上操作
    dirty = _sp.run(['git', 'status', '--porcelain'],
                    capture_output=True, text=True, check=False).stdout.strip()
    if dirty and not args.allow_dirty:
        print('错误: 工作区有未提交改动。请先 git stash / git commit 再 '
              'import-review，或加 --allow-dirty 强行继续。', file=sys.stderr)
        print(dirty, file=sys.stderr)
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

    # 4. media bundle — 从 docx 再读一次（简化；后续任务可合并 API）
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
    print(f'   手动合并： git merge --no-ff {branch_ref.replace("refs/heads/", "")}')


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
```

在 subparsers 尾部追加：
```python
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
```

在 dispatch 处追加：
```python
    elif args.command == 'import-review':
        cmd_import_review(args)
```

- [ ] **Step 4: 跑测试通过**

Run: `python3.14 -m pytest tests/test_cli_review.py -v`
Expected: 4 passed。

- [ ] **Step 5: commit**

```bash
git add cli.py tests/test_cli_review.py
git commit -m "$(cat <<'EOF'
feat(cli): import-review 子命令 — 审校 docx → review 分支 commit

调 resolve_baseline 四级回退找基线；用 ANTHROPIC_API_KEY 在时构建真实
classify client，否则降级为 opinion；make_edits_with_comments + apply +
render_commit_message → commit_to_review_branch，不动 HEAD。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Stage G — 测试矩阵补齐与文档

### Task 27: roundtrip 测试 + 持久 fixtures 生成脚本

**Files:**
- Create: `tests/test_roundtrip.py`
- Create: `tests/fixtures/README.md`
- Create: `tests/build_fixtures.py`
- Create: `tests/fixtures/minimal.md`
- Create: `tests/fixtures/minimal_edited.md`

**策略：** `reviewed_tracked.docx` 可以直接用 `md_diff_docx.diff_md_files(minimal.md, minimal_edited.md)` 自动生成；`reviewed_plain.docx` / `reviewed_comments.docx` / `reviewed_mixed.docx` 要手工在 Word 里保存——在 `tests/fixtures/README.md` 留详细说明。

- [ ] **Step 1: 新建 `tests/fixtures/minimal.md`**

```markdown
# 第 1 章  测试章节

## 1.1 第一节

这是第一段内容，用来测试 track changes。

- 列表项一
- 列表项二
- 列表项三

| 列A | 列B |
|---|---|
| 1 | 2 |

$$x + y = z$$

```python
print(1)
```
```

- [ ] **Step 2: 新建 `tests/fixtures/minimal_edited.md`**

```markdown
# 第 1 章  测试章节

## 1.1 第一节（改名）

这是第一段修改后的内容，用于 track changes 测试。

- 列表项一
- 列表项二改
- 列表项三

| 列A | 列B |
|---|---|
| 1 | 22 |

$$x + y = 2z$$

```python
print(2)
```
```

- [ ] **Step 3: 新建 `tests/build_fixtures.py`**

```python
"""tests/build_fixtures.py — 再生所有可自动合成的 fixtures。

用法：
  python3.14 tests/build_fixtures.py
"""
import os
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
```

- [ ] **Step 4: 新建 `tests/fixtures/README.md`**

```markdown
# tests/fixtures/

测试用 fixture。

## 可自动再生

运行 `python3.14 tests/build_fixtures.py` 会重生成：

- `reviewed_tracked.docx` — 由 `minimal.md` → `minimal_edited.md` 的 diff
  生成的 Track Changes docx。

## 需手工制作

下面这些需要在 Word 里打开 `reviewed_tracked.docx` 另存，构造为：

- `reviewed_plain.docx` — 把 `reviewed_tracked.docx` 里所有修订点"接受"
  （Accept All），另存为此文件，模拟"不开 Track Changes 直接改"。
- `reviewed_comments.docx` — 在 `minimal.md` 导出的干净 docx 里
  （用 `python3.14 cli.py convert tests/fixtures/minimal.md -o minimal.docx`
  得到），针对"第一段"插入 2-3 条批注（既有明确修改指令，也有意见），另存为此文件。
- `reviewed_mixed.docx` — 在 `reviewed_tracked.docx` 基础上再补 1-2 条批注。

如果缺失这些手工 fixtures，相关测试会被 pytest.mark.skip 跳过
（见 `tests/test_roundtrip.py` 的 `pytest.importorskip` 类似模式）。
```

- [ ] **Step 5: 新建 `tests/test_roundtrip.py`**

```python
"""roundtrip 测试：export-review → (模拟审校) → import-review。

只覆盖"机器可完成"的那部分：用 minimal.md → minimal_edited.md 生成
reviewed_tracked.docx，再直接 import-review 进 tmp 仓库，看 review 分支
的 commit 内容等于 minimal_edited.md。

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

    # review 分支内容应接近 minimal_edited.md
    branch_name = None
    for line in subprocess.check_output(
            ['git', 'branch'], cwd=tmp_git_repo, text=True).splitlines():
        if 'review/ceshiyuan' in line:
            branch_name = line.strip().lstrip('* ').strip()
            break
    assert branch_name is not None

    new_md = subprocess.check_output(
        ['git', 'show', f'{branch_name}:minimal.md'],
        cwd=tmp_git_repo, text=True)
    # 不要求字节级相等（文本表达有歧义），只要求关键改动出现
    expected = (fixtures_dir / 'minimal_edited.md').read_text(encoding='utf-8')
    # 提取几个标志性改动
    assert '改名' in new_md
    assert '修改后的内容' in new_md or '修改' in new_md
    _ = expected


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
```

- [ ] **Step 6: 先把 fixture build 跑一次**

Run: `python3.14 tests/build_fixtures.py`
Expected: `✅ 生成 .../tests/fixtures/reviewed_tracked.docx`

- [ ] **Step 7: 跑所有测试**

Run: `python3.14 -m pytest tests/ -v`
Expected: 全部 passed，roundtrip_plain_if_available 可能 skip（手工 fixtures 缺失时）。

- [ ] **Step 8: commit**

```bash
git add tests/fixtures/ tests/build_fixtures.py tests/test_roundtrip.py
git commit -m "$(cat <<'EOF'
test: roundtrip + tests/build_fixtures.py

minimal.md + minimal_edited.md + build_fixtures.py 能自动生成
reviewed_tracked.docx；roundtrip 测试用该 docx 跑一次 export/import 链路。
reviewed_plain/comments/mixed 需手工制作，缺失时 test 走 skip 而非失败。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 28: `tests/smoke.sh`

**Files:**
- Create: `tests/smoke.sh`

- [ ] **Step 1: 写 smoke 脚本**

Create `tests/smoke.sh`:
```bash
#!/usr/bin/env bash
# tests/smoke.sh — 审校桥 smoke 脚本
#
# 验证：
#   1. init tmp git repo + 提交 minimal.md
#   2. 修改 minimal.md → minimal_edited.md 并 commit
#   3. export-review HEAD → 得到 <sha>.docx 且 custom.xml 含 SourceGitCommit
#   4. import-review 产出 review/ceshiyuan-<date> 分支 + 正确 author
#
# 用法：bash tests/smoke.sh

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "== smoke: 临时仓库 $TMP"

git -C "$TMP" init -q -b main
git -C "$TMP" config user.email 'smoke@example.com'
git -C "$TMP" config user.name 'Smoke'
git -C "$TMP" config commit.gpgsign false

cp "$HERE/fixtures/minimal.md" "$TMP/chapter.md"
git -C "$TMP" add chapter.md
git -C "$TMP" commit -q -m 'v1'
echo '{"last_exported_sha":null,"last_exported_at":null,"exports":[]}' > "$TMP/.review_state.json"

cp "$HERE/fixtures/minimal_edited.md" "$TMP/chapter.md"
git -C "$TMP" add chapter.md
git -C "$TMP" commit -q -m 'v2'

HEAD_SHA=$(git -C "$TMP" rev-parse HEAD)
SHORT=${HEAD_SHA:0:7}

echo "== smoke: export-review HEAD"
( cd "$TMP" && python3.14 "$ROOT/cli.py" export-review HEAD --path chapter.md )

DOCX="$TMP/chapter_${SHORT}.docx"
test -f "$DOCX" || { echo "FAIL: 送审 docx 未生成: $DOCX"; exit 1; }

# 用 unzip -p 看 custom.xml 含 SourceGitCommit
unzip -p "$DOCX" docProps/custom.xml | grep -q 'SourceGitCommit' \
  || { echo "FAIL: custom.xml 无 SourceGitCommit"; exit 1; }

echo "== smoke: import-review $DOCX --reviewer 测试员"
HEAD_BEFORE=$(git -C "$TMP" rev-parse HEAD)
( cd "$TMP" && python3.14 "$ROOT/cli.py" import-review "$DOCX" --reviewer 测试员 )

# HEAD 未被切走
HEAD_AFTER=$(git -C "$TMP" rev-parse HEAD)
[ "$HEAD_BEFORE" = "$HEAD_AFTER" ] || { echo "FAIL: HEAD 被改动 $HEAD_BEFORE → $HEAD_AFTER"; exit 1; }

# 找 review 分支
BRANCH=$(git -C "$TMP" branch | grep 'review/ceshiyuan' | head -n1 | sed 's/^\*\? *//')
[ -n "$BRANCH" ] || { echo "FAIL: 未找到 review/ceshiyuan-* 分支"; exit 1; }

# 验证 author
AUTHOR=$(git -C "$TMP" log -1 --pretty='%an' "$BRANCH")
[ "$AUTHOR" = "测试员" ] || { echo "FAIL: author=$AUTHOR, 期望 测试员"; exit 1; }

# 验证 committer
CN=$(git -C "$TMP" log -1 --pretty='%cn' "$BRANCH")
[ "$CN" = "md-docx-bridge" ] || { echo "FAIL: committer=$CN"; exit 1; }

echo "== smoke: PASS"
```

- [ ] **Step 2: 赋可执行权限并运行**

Run:
```bash
chmod +x tests/smoke.sh
bash tests/smoke.sh
```
Expected: 最后输出 `== smoke: PASS`。

- [ ] **Step 3: commit**

```bash
git add tests/smoke.sh
git commit -m "$(cat <<'EOF'
test: tests/smoke.sh — 审校桥端到端冒烟

创建 tmp 仓库 → export-review HEAD → 断言 custom.xml 含 SourceGitCommit →
import-review → 断言 HEAD 未变、review/ceshiyuan-* 分支存在、author/
committer 正确。不依赖任何网络或手工 fixture。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 29: `README.md` — 从 `README_md2docx.md` 扩写

**Files:**
- Create (or replace): `README.md`
- Keep: `README_md2docx.md`（保留作为便捷子集，但 README.md 是主文档）

- [ ] **Step 1: 读现有 README_md2docx.md 以确认范围**

Run: `cat README_md2docx.md`
Note: 用作新 README 的前置章节基础。

- [ ] **Step 2: 写 `README.md`**

```markdown
# md ↔ docx 审校桥

DeepSeek 工程实现分析一书的写作工具链。核心能力：
1. `cli.py convert`：md → docx（含 LaTeX 公式转 OMML 和 13 条出版规范）
2. `cli.py diff`：两个 md 文件差异 → Word 修订文档
3. `cli.py export-review`：按 git commit 差异生成带 Track Changes 的送审 docx
4. `cli.py import-review`：把审校者改过的 docx 回灌为 `review/` 分支的 git commit（不动 main）

## 环境

- **必须 Python 3.10+**。本项目用了 `X | Y` 联合类型。Mac 自带 `/usr/bin/python3` 是 3.9，会报 `TypeError`。
- 本地推荐 `/opt/homebrew/bin/python3.14`（`python3.14` 命令）。
- 安装依赖：
  ```bash
  python3.14 -m pip install --user --break-system-packages -r requirements.txt
  ```

可选（运行时探测）：
- `libreoffice`：公式截图（无则降级，送审 docx 不受影响）
- 环境变量 `ANTHROPIC_API_KEY`：批注 LLM 分类（无则全部降级为 opinion）

## 常用命令

### 送审 — md commit 差异 → docx

```bash
# 以 HEAD 相对 HEAD~1
python3.14 cli.py export-review HEAD --path chapter3_new.md

# 任意 commit 范围
python3.14 cli.py export-review c269457..6f7da18 --path chapter3_new.md

# 上次送审之后的累积改动
python3.14 cli.py export-review --since-last-review --path chapter3_new.md
```

输出 `chapter3_new_<head_sha7>.docx`，`docProps/custom.xml` 含 `SourceGitCommit/SourceBaseCommit/SourcePath/ReviewExportedAt`，`.review_state.json` 记录送审历史。

### 回灌 — 审校 docx → review/ 分支 commit

```bash
# 典型：基线从 custom.xml 自动识别
python3.14 cli.py import-review chapter3_new_6f7da18_reviewed.docx --reviewer "张三"

# 基线丢失的兜底
python3.14 cli.py import-review random.docx \
  --base 6f7da18 --path chapter3_new.md --reviewer "张三"
```

产出 `review/zhangsan-20260423[-N]` 分支上的一个 commit，author 为审校者，committer 为 `md-docx-bridge`。**HEAD 不动，main 工作区不动。**

### 合并 review 分支（手动）

```bash
git log review/zhangsan-20260423
git diff main..review/zhangsan-20260423
git merge --no-ff review/zhangsan-20260423
```

## 审校工作流

1. 作者 commit md 的改动到 main。
2. 作者 `export-review` 生成 `chapter_<sha>.docx`，发给审校者。
3. 审校者在 Word 里打开，支持三种审校方式：
   - **Track Changes**（推荐）：修订模式直接改。
   - **直接改**（不开 Track Changes）：回灌时会和基线比对出差异。
   - **Comments**：在不便直接改的地方写批注；LLM 会分类为"明确修改指令"还是"意见"。
4. 审校者把改好的 docx 发回作者。
5. 作者 `import-review` 生成 `review/<reviewer>-<date>` 分支上的 commit。
6. 作者人工 review + `git merge --no-ff` 入 main。

## Comments 的 LLM 分类

每条 Word 批注走 Claude Sonnet 4.6 分类（需 `ANTHROPIC_API_KEY`）：
- `kind=edit` 且 `confidence >= 0.7` → 并入文本修改
- 其他 → 在 md 的锚点附近插入 `<!-- REVIEWER[姓名]: 批注文字 -->` HTML 注释

`confidence` 阈值可在 `docx_to_md.EDIT_CONFIDENCE_THRESHOLD` 调整。

## 模块结构

```
cli.py                    # 统一入口，4 个子命令
md_core.py                # md → docx + Block IR
md_formatter.py           # 13 条出版规范合规层
md_diff_docx.py           # md↔md diff → Word Track Changes
docx_reader.py            # docx → Block IR（revisions + comments）
docx_to_md.py             # 基线 vs 审校 → MdEdit → 写 md
git_review.py             # git 封装（read_at / 四级回退 / plumbing commit）
comment_classifier.py     # Claude API 批注分类
MML2OMML.XSL              # LaTeX 公式转 Word OMML 的 XSL
upload_to_feishu.py       # 上传飞书（独立）
legacy/                   # 历史 md2docx*.py 归档（请勿使用）
```

## 测试

```bash
python3.14 -m pytest tests/ -v      # 单测
bash tests/smoke.sh                 # 端到端冒烟
python3.14 tests/build_fixtures.py  # 再生可合成的 fixture docx
```

### 手工 fixtures

`reviewed_plain.docx` / `reviewed_comments.docx` / `reviewed_mixed.docx` 需在 Word 里制作。见 `tests/fixtures/README.md`。

## 设计文档

- 设计 spec：`docs/superpowers/specs/2026-04-23-md-docx-revision-bridge-design.md`
- 实现计划：`docs/superpowers/plans/2026-04-23-md-docx-revision-bridge.md`
- 项目续接指南：`CLAUDE.md`

## 已知限制

- OMML → LaTeX 反向转换**未实现**。公式被改时只产占位注释 + 片段 docx / 截图。
- 多文件批量送审 / 自动合并 review 分支 / CI 集成 — 未做。
- Web UI — 未做。
```

- [ ] **Step 3: 保留旧 `README_md2docx.md` 但改成链到新 README**

编辑 `README_md2docx.md`，在开头加一行：
```markdown
> 本文档已并入主 [README.md](./README.md)，此处仅保留供历史引用。
```

- [ ] **Step 4: commit**

```bash
git add README.md README_md2docx.md
git commit -m "$(cat <<'EOF'
docs: README.md 扩写为 md↔docx 审校桥主文档

覆盖 convert/diff/export-review/import-review 四个子命令的用法、
审校工作流、LLM 分类阈值、模块结构、测试、设计文档索引。
README_md2docx.md 保留但指向新 README。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## 完成条件（DoD）

本计划执行完成的硬指标：

1. `python3.14 -m pytest tests/ -v` 全 PASS（手工 fixture 缺失的 3 个用例可 SKIP）。
2. `bash tests/smoke.sh` 最后一行打印 `== smoke: PASS`。
3. `python3.14 cli.py convert chapter3_new.md -o /tmp/ch3.docx` 正常输出 413/413 公式（回归未破坏主线）。
4. `python3.14 cli.py export-review HEAD --path chapter3_new.md` 能生成 `chapter3_new_<sha7>.docx` 且 `unzip -p <file> docProps/custom.xml` 含 `SourceGitCommit`。
5. 用上述 docx 做 `python3.14 cli.py import-review <file> --reviewer 测试员` 可在 `review/ceshiyuan-<date>` 分支上得到一个 commit，HEAD 仍在 main。
6. `git status` 干净；`git log --oneline -30` 可见 29 个 Task 的独立 commit（顺序、中文 title、都带 Co-Authored-By）。
7. `CLAUDE.md` §4 的 Task 8（主线 in_progress）可改为 completed。

## 如何停下来 / 出问题时

- 测试在某 Task 失败不要继续。**原地排错**，必要时把测试"降级为 xfail"绝对不允许 — 那会让后续任务基于错误前提推进。
- 若一个 Task 的测试揭示 spec 本身有错，**先改 spec 再改代码**。spec 路径：`docs/superpowers/specs/2026-04-23-md-docx-revision-bridge-design.md`。
- 任何 `git reset --hard` / `git push --force` / `rm -rf` 必须在本 Task 范围内**先确认**再执行。







