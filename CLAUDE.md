# CLAUDE.md — 项目上下文与续接指南

> 本文件给下一个 Claude / 开发者看，帮助快速续接"md ↔ docx 审校桥"这项工作。
> 不要把它当 README 给终端用户看——那是 `README_md2docx.md` 的职责。

## 1. 这个项目在做什么

**DeepSeek 工程实现分析**一书的写作仓库。核心产物是 `chapter3_new.md`（还会有更多章节），
需要 md→docx 导出送审，以及把审校者改过的 docx 回灌成 md git commit。

**当前已完成的能力**（现行主线代码，不要重写）：
- `md_core.py`：Markdown → Block IR → DOCX，含 LaTeX→MathML→OMML 公式转换（413/413 验证通过）
- `md_formatter.py`：13 条写作规范渲染层（三线表、图表/代码清单编号等）
- `md_diff_docx.py`：md↔md block diff → Word Track Changes / Comments
- `cli.py`：统一入口，`convert` + `diff` 两个子命令
- `MML2OMML.XSL`：LaTeX 公式转 Word 公式的 XSL 模板
- `upload_to_feishu.py`：上传到飞书文档的独立脚本

**历史遗留**（功能已被主线覆盖，本次工作要迁 `legacy/`）：
- `md2docx.py` / `md2docx_improved.py` / `md2docx_v2.py` / `md2docx_latex.py`

## 2. 运行环境注意事项

- **必须用 Python 3.10+**。项目代码用了 `X | Y` 联合类型（PEP 604）。系统默认 `/usr/bin/python3` 是 3.9，会报 `TypeError: unsupported operand type(s) for |: 'type' and 'type'`。
- 本机可用的新版 Python：`/opt/homebrew/bin/python3.14`
- 已安装到 3.14 的依赖：`python-docx`、`latex2mathml`（均为 `--user --break-system-packages`）
- 转换 chapter3_new.md 的实际命令：
  ```bash
  python3.14 cli.py convert chapter3_new.md -o chapter3_new.docx
  ```

## 3. 当前正在做的工作：md ↔ docx 审校桥

### 3.1 需求（用户原话）

1. 项目是 md↔docx 相互转换。
2. 公式转换已完成（指 `md_core.py`），请仔细读现有代码再合并（指把旧 `md2docx*.py` 迁到 `legacy/`）。
3. md 文档通过 git diff 在 commit 间记录差异；docx 文档用修订（Track Changes）方案。
4. 需要把审校者在 docx 里的修订转为 md 的 diff 写入 git。
5. 需要把 md 某次 commit 的改动转成 docx 修订送人工审。

### 3.2 设计决策（已与用户确认）

| 决策点 | 选择 |
|--------|------|
| 旧 `md2docx*.py` 如何处理 | **B**：迁移到 `legacy/` 目录保留历史 |
| 审校模式支持范围 | **D**：Track Changes + 不开 Track Changes 直接改 + Comments 三种都要 |
| 审校结果落点 | 提交到 `review/<reviewer-slug>-<YYYYMMDD>[-<N>]` 分支，**用户手动合并**，工具不触 main |
| 公式/表格/图片回灌分级 | 公式改 → 占位 `<!-- REVIEW: formula changed, see attachments/N.png -->` + 截图；表格单元格改 → 精确 cell 替换；表格结构改 → 整块替换；图片改 → sha256 存 `typora-user-images/img-<sha8>.png` 并改路径 |
| Word Comments 分流 | 涉及改正文的进 diff/commit；纯意见转 `<!-- REVIEWER[姓名]: ... -->` |
| 判别 comment 类型 | **B**：调 Claude API 分类（model `claude-sonnet-4-6`，启用 prompt caching），置信度 ≥0.7 且 kind=='edit' 才改正文，否则 opinion |
| 基线追踪 | **D**：四级回退链 = custom.xml 元数据 → 文件名 `*_<sha7>.docx` → sidecar `.docx.base` → CLI `--base`，都失败则报错 |
| 送审入口 | **a+b+d**：`export-review <commit>` + `<base>..<head>` + `--since-last-review` |

### 3.3 已交付的产物

- `docs/superpowers/specs/2026-04-23-md-docx-revision-bridge-design.md`（474 行，commit `eda4685`）
  这是**唯一真相来源**。实现计划、代码、测试都必须以此为准。
- `CLAUDE.md`（本文件）

### 3.4 待交付的产物

**还没写的代码**（按依赖顺序）：

1. `legacy/` 目录 + 把 `md2docx*.py` 4 个文件 `git mv` 进去
2. `md_core.py` 的 `Block` 类追加 `revisions: List[Revision]` 和 `comments: List[Comment]`（带 `field(default_factory=list)` 默认值保证向后兼容）
3. `requirements.txt` + `.review_state.json` 初始化
4. `git_review.py`：`read_at()` / `resolve_range()` / `stamp_docx_metadata()` / `resolve_baseline()` / `detect_reviewer()` / `commit_to_review_branch()`
5. `docx_reader.py`：docx → Block IR（paragraph / heading / list / code / table / equation / figure / comment）
6. `comment_classifier.py`：调 Claude API 分类批注（Sonnet 4.6 + prompt caching + error fallback）
7. `docx_to_md.py`：两轮块匹配 + 分级 MdEdit 生成 + 逆序应用 + commit message 模板
8. `cli.py` 扩展：`export-review` 和 `import-review` 子命令
9. `tests/`：fixtures + 每模块单测 + smoke 脚本
10. `README.md`（扩写自 `README_md2docx.md`）新增审校工作流一节

### 3.5 明确排除（不在本次范围）

- OMML→LaTeX 反向转换（无可靠开源库，用占位+截图绕过）
- 方案 2 的"中立 IR 重构"（任务 #9 已归档为未来工作）
- Web UI / 多文件批量 / 自动 merge review 分支 / CI 集成

## 4. 任务跟踪状态

TaskTool 里现有的任务（ID 不可跨会话保留，仅作参考）：

| ID | Status | 说明 |
|----|--------|------|
| 1–7 | completed | 探索/澄清/提案/设计/写 spec/自查/用户 review |
| 8 | **in_progress** | Transition to implementation（即当前断点） |
| 9 | pending（deferred） | 方案 2：中立 IR 重构 |

## 5. 恢复工作时的第一步

上次断在 `writing-plans` skill 里——skill 已经加载（announce 也发了），但实现计划文档 `docs/superpowers/plans/2026-04-23-md-docx-revision-bridge.md` **还没生成**。

### 续接动作

```
# 1. 查看设计 spec（必读）
docs/superpowers/specs/2026-04-23-md-docx-revision-bridge-design.md

# 2. 重新进入 writing-plans skill
Skill superpowers:writing-plans

# 3. 按 spec 写出 bite-sized TDD 任务计划到：
docs/superpowers/plans/2026-04-23-md-docx-revision-bridge.md

# 4. 写完做 self-review（placeholder / 类型一致 / spec 覆盖）

# 5. 和用户确认执行方式：
#    - subagent-driven-development（推荐，每任务派子 agent）
#    - executing-plans（内联执行）

# 6. 开写代码，严格 TDD，频繁 commit
```

### 计划文档草拟建议（从 spec §3-§10 直接映射出来的任务分组）

**Stage A — 准备**（3 个任务）
- Task 1: `git mv` 四个旧脚本到 `legacy/`，新建 `legacy/README.md`
- Task 2: 扩展 `md_core.Block`（加 `Revision`/`Comment` dataclass + 两字段），写向后兼容测试
- Task 3: `requirements.txt` + `.review_state.json` 初始骨架 + `tests/conftest.py`（init tmp git repo fixture）

**Stage B — `git_review.py`**（5 个任务）
- Task 4: `read_at(sha, path)` + `resolve_range()`（支持 `<commit>` / `<base>..<head>` / `--since-last-review`）
- Task 5: `stamp_docx_metadata()` 写 docProps/custom.xml
- Task 6: `resolve_baseline()` 四级回退
- Task 7: `detect_reviewer()` + 中文→拼音 slug + 分支命名冲突处理
- Task 8: `commit_to_review_branch()` 用 `git hash-object` + `mktree` + `commit-tree` + `update-ref`（不切 HEAD）

**Stage C — `docx_reader.py`**（6 个任务）
- Task 9: 读 paragraph（accepted text + revisions 列表）
- Task 10: 读 heading / list / code
- Task 11: 读 table（cells + structure）
- Task 12: 读 equation（OMML XML 指纹 = 规范化后 sha256）
- Task 13: 读 figure（从 word/media 抽二进制 + 记录 sha256）
- Task 14: 读 comments（word/comments.xml + commentRangeStart/End 锚点）

**Stage D — `comment_classifier.py`**（1 个任务）
- Task 15: `classify()` 走注入的 `Anthropic` 客户端，带 prompt caching；API/JSON 失败降级为 opinion；无 `ANTHROPIC_API_KEY` 也降级。测试用 mock。

**Stage E — `docx_to_md.py`**（7 个任务）
- Task 16: `BlockMatch` / `MdEdit` dataclass + 两轮块匹配算法
- Task 17: paragraph / heading 的 MdEdit 生成
- Task 18: list / code 的 MdEdit 生成
- Task 19: table diff（同形状走 cell / 不同形状整块）
- Task 20: figure diff（新图 sha256 落盘 + 改 md path）
- Task 21: equation diff（→占位 + 片段 docx 或 libreoffice 截图）
- Task 22: comment 经 classifier 分流 → MdEdit
- Task 23: `apply_edits_to_md()` 倒序应用 + 冲突检测
- Task 24: commit message 模板渲染

**Stage F — CLI**（2 个任务）
- Task 25: `cli.py export-review`
- Task 26: `cli.py import-review`

**Stage G — 测试与文档**（3 个任务）
- Task 27: fixtures 生成脚本（minimal.md + 用 md_diff_docx 生成 reviewed_tracked.docx；reviewed_plain/comments/mixed 需手动 OOXML 拼或提供指南）
- Task 28: `tests/smoke.sh`
- Task 29: `README.md`（从 `README_md2docx.md` 扩写）审校工作流章节

## 6. 关键技术要点（续接时容易踩的坑）

### 6.1 Block 字段扩展的向后兼容

```python
@dataclass
class ParagraphBlock:
    text: str
    raw: str
    revisions: List[Revision] = field(default_factory=list)
    comments: List[Comment]   = field(default_factory=list)
```

`md_core.py` 现在所有构造点 `ParagraphBlock(text=..., raw=...)` 不传新字段仍然成立。**必须**写测试固化这一点。

### 6.2 不切 HEAD 的 commit 写入

用 plumbing 命令链：

```bash
blob=$(git hash-object -w --stdin < new.md)                   # 写 blob
tree=$(echo "100644 blob $blob\tchapter3_new.md" | git mktree) # 建 tree
commit=$(GIT_AUTHOR_NAME=张三 GIT_AUTHOR_EMAIL=zhangsan@review.local \
         GIT_COMMITTER_NAME=md-docx-bridge GIT_COMMITTER_EMAIL=bridge@review.local \
         git commit-tree $tree -p $base_sha -m "...")          # 建 commit
git update-ref refs/heads/review/zhangsan-20260423 $commit     # 建/动分支
```

**不要** `git checkout` 或 `git branch` 切到 review 分支——会扰动 main 的工作区。

### 6.3 OMML 指纹（判断公式是否改过）

不要字节级比较——Word 会塞不同的 `<w:rPr>` 属性。先规范化：

```python
def _canonical_omml(omath_element) -> str:
    # 剥 <w:rPr> 里的字体属性，剥 xml:space 属性，排序属性
    # 然后 etree.tostring(..., method='c14n') 做规范化 XML
    return canonical_bytes.decode('utf-8')

fingerprint = hashlib.sha256(_canonical_omml(omath).encode()).hexdigest()
```

### 6.4 Comment 锚点定位

`word/document.xml` 里：

```xml
<w:p>
  <w:r><w:t>这段话有问题</w:t></w:r>
  <w:commentRangeStart w:id="0"/>
  <w:r><w:t>需要批注的文字</w:t></w:r>
  <w:commentRangeEnd w:id="0"/>
  <w:r><w:commentReference w:id="0"/></w:r>
</w:p>
```

读 block 时，遇 `commentRangeStart` 记开始字符偏移，遇 `End` 记结束，组成 `Comment.anchor_range`；批注正文在 `word/comments.xml`。

### 6.5 LLM 分类的 prompt caching

```python
response = client.messages.create(
    model='claude-sonnet-4-6',
    system=[
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},   # ← 这里
        }
    ],
    messages=[{"role": "user", "content": USER_PROMPT.format(...)}],
    max_tokens=500,
)
```

### 6.6 Chapter 3 的 image 引用已全部本地化

`chapter3_new.md` 里所有 `![...](url)` 都指向 `./typora-user-images/`，**不要**再回去改成外链。
`typora-user-images/` 已从 git 索引移除（仍在 .gitignore）但本地保留——所有图片都在本地可用。

## 7. 偏好与约定（已与用户确立）

- **自动模式**：用户开着 auto mode，倾向"直接干活少打断"。但 **git push / destructive 操作仍要确认**。
- **commit 风格**：中文 title + 英文 Co-Authored-By，用 HEREDOC 确保格式。最近示例见 `git log -5`。
- **push 策略**：之前 main 分支禁止直接 push，已被用户显式 allow（`/permissions` 批准了 "Push to GitHub"）。
- **图片命名**：aliyun 拷过来的保留原 hash 名；GitHub 下载的用描述性名如 `eplb_example.png`。
- **回答语言**：中文为主，技术词英文穿插即可。

## 8. 快速启动命令清单

```bash
# 转换 chapter3_new.md → docx（验证现有链路还工作）
python3.14 cli.py convert chapter3_new.md -o chapter3_new.docx

# 查看本次设计 spec
cat docs/superpowers/specs/2026-04-23-md-docx-revision-bridge-design.md

# 看上次送审/回灌状态（如已实现）
cat .review_state.json 2>/dev/null || echo "尚未创建"

# 运行测试（如已写）
python3.14 -m pytest tests/ -v

# 运行 smoke（如已写）
bash tests/smoke.sh
```
