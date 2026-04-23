# md ↔ docx 审校桥设计

日期：2026-04-23
状态：设计完成，待实现
作者：gaozhi + Claude

## 1. 目标

在现有 md→docx 转换工具链之上，建立完整的"审校双向桥"：

1. **送审**：把 md 文件的任意一次（或一段）git commit 的改动，生成带 Word Track Changes 的 docx，交给审校者。
2. **回灌**：把审校者改过的 docx（含 Track Changes / 纯文本改动 / Comments 三种模式）解析成对 md 的修改集，以审校者为 author 在 `review/<reviewer>-<date>` 分支上提交。
3. **不破坏主线**：main 分支上的变动完全由人手动 merge，工具绝不直接写 main。

## 2. 范围

### 本次交付
- docx → Block IR 的读取（`docx_reader.py`）
- 基线 docx vs 审校 docx 的分级比较与 md patch 生成（`docx_to_md.py`）
- git 状态管理（基线四级回退、review 分支创建、commit 作者）（`git_review.py`）
- LLM 批注分类（`comment_classifier.py`）
- 扩展 `cli.py` 子命令：`export-review` / `import-review`
- 迁移四个旧脚本到 `legacy/`
- 完整测试矩阵与 smoke 脚本

### 明确排除
- OMML → LaTeX 反向转换（公式被改时走占位 + 截图）
- 方案 2 的中立 IR 重构（归档为未来工作）
- Web UI / 审校门户
- 多文件批量送审
- 自动 merge review 分支
- CI 集成（smoke 脚本备好即可）

## 3. 模块架构

```
deepseek-book/
├── cli.py                       # [改] 新增 export-review / import-review
├── md_core.py                   # [保留] Block IR + md→docx
├── md_formatter.py              # [保留] 13 条规范渲染层
├── md_diff_docx.py              # [保留] md↔md diff → Word
│
├── docx_reader.py               # [新] docx → Block IR（含 revisions/comments）
├── docx_to_md.py                # [新] 基线 vs 审校 → MdEdit → 写 md
├── git_review.py                # [新] git 封装 + 基线四级回退
├── comment_classifier.py        # [新] Claude API 分类批注
│
├── legacy/                      # [新] 迁入旧脚本
│   ├── md2docx.py
│   ├── md2docx_improved.py
│   ├── md2docx_v2.py
│   └── md2docx_latex.py
│
├── MML2OMML.XSL                 # [保留]
├── upload_to_feishu.py          # [保留]
├── requirements.txt             # [新]
├── .review_state.json           # [新] 审校状态（last_exported_sha 等）
│
├── tests/                       # [新] 完整测试矩阵
└── docs/superpowers/specs/      # [新] 本文件
```

### 模块边界
- `md_core` 保持 md→docx 单向 + IR 定义；不膨胀到 docx→md。
- `docx_reader` 输出 `md_core.Block`（同一 dataclass），通过向 Block 追加可选字段 `revisions`/`comments`。
- `docx_to_md` / `git_review` / `comment_classifier` 通过函数签名通信，不共享全局状态。
- `cli.py` 是唯一对外入口。

## 4. 数据流

### 4.1 export-review（md commit → docx）

```
cli.py export-review <commit> | <base>..<head> | --since-last-review
  │
  ├─ git_review.resolve_range() → (old_sha, new_sha)
  ├─ git_review.read_at(sha, path) × 2     # git show
  ├─ md_core.parse_md_blocks × 2           # 两版本 Block
  ├─ md_diff_docx.DiffDocxRenderer         # 已有，track-changes
  ├─ 写 docx → git_review.stamp_docx_metadata()
  │    custom.xml: SourceGitCommit / SourceBaseCommit / SourcePath / ReviewExportedAt
  ├─ 文件名：<basename>_<new_sha_7>.docx
  └─ 更新 .review_state.json.last_exported_sha
```

`.review_state.json` 结构：
```json
{
  "last_exported_sha": "6f7da18",
  "last_exported_at": "2026-04-23T16:37:00Z",
  "exports": [
    { "sha": "6f7da18", "file": "chapter3_6f7da18.docx", "base": "c269457" }
  ]
}
```
文件 commit 到 main，允许多机协作。

### 4.2 import-review（reviewed.docx → md commit）

```
cli.py import-review <reviewed.docx> [--reviewer "张三"] [--base <sha>]
  │
  ├─ git_review.resolve_baseline(docx_path)      # 四级回退
  │    1. custom.xml SourceGitCommit（40 位 sha）
  │    2. 文件名 *_<sha7>.docx
  │    3. sidecar <path>.docx.base
  │    4. CLI --base
  │    都失败 → exit(1) 提示 --base --path
  │
  ├─ 重新生成基线 docx（防篡改）：
  │    git show base_sha:<path>.md → md_core.convert → baseline.docx（tmp）
  │
  ├─ docx_reader.read(baseline.docx)  → baseline_blocks
  ├─ docx_reader.read(reviewed.docx)  → reviewed_blocks
  │
  ├─ docx_to_md.diff_blocks(baseline, reviewed)
  │    → text_patches / struct_changes / comments（三路）
  │
  ├─ 逐条 comment → comment_classifier.classify()
  │    edit & confidence>=0.7 → 并入 text_patches
  │    其他 → 变成 <!-- REVIEWER[...]: ... --> 注释
  │
  ├─ docx_to_md.apply_to_md() 生成 MdEdit 列表
  │    按分级策略处理（见 §6）
  │    按 target_line_range 倒序应用到基线 md 文本
  │
  └─ git_review.commit_to_review_branch()
       分支：review/<reviewer-slug>-<YYYYMMDD>[-<N>]
       author=审校者, committer=md-docx-bridge
       不切换 HEAD（git commit-tree + update-ref）
```

## 5. 关键数据结构

### 5.1 扩展 md_core.Block（向后兼容）

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
    anchor_range: Tuple[int, int]    # Block text 内字符偏移

# 每个 Block 追加带默认值的字段：
revisions: List[Revision] = field(default_factory=list)
comments: List[Comment]   = field(default_factory=list)
```

### 5.2 docx_reader 输出语义

`read_docx(path)` 返回的 Block 列表：
- `Block.text/latex/code` 是"接受所有修订后的最终文本"（`<w:ins>` 视为已存在，`<w:del>` 视为已删除）
- 原始 `<w:ins>/<w:del>` 保留在 `Block.revisions`
- 批注按锚点所在 Block 挂在 `Block.comments`

### 5.3 docx_to_md 中间结构

```python
@dataclass
class BlockMatch:
    base_block: Optional[Block]
    reviewed_block: Optional[Block]
    kind: Literal['equal', 'text_edit', 'struct_change', 'insert', 'delete']

@dataclass
class MdEdit:
    target_line_range: Tuple[int, int]   # 基线 md 行号 [start, end)
    replacement: str                     # 空串=删除
    reason: str                          # text_edit|formula_changed|figure_replace|
                                         # comment_edit|comment_opinion|insert|delete|...
    provenance: str                      # 来源说明（用于 commit message）
```

### 5.4 custom.xml 基线元数据

```xml
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
            xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" name="SourceGitCommit">
    <vt:lpwstr>6f7da18a1b2c3d4e5f...</vt:lpwstr>
  </property>
  <property fmtid="..." pid="3" name="SourceBaseCommit"><vt:lpwstr>c269457</vt:lpwstr></property>
  <property fmtid="..." pid="4" name="SourcePath"><vt:lpwstr>chapter3_new.md</vt:lpwstr></property>
  <property fmtid="..." pid="5" name="ReviewExportedAt"><vt:lpwstr>2026-04-23T16:37:00Z</vt:lpwstr></property>
</Properties>
```
`SourceGitCommit` 用完整 40 位 sha（避免歧义）；文件名回退用 7 位 short sha（可读）。

## 6. 块匹配与分级处理（回灌核心算法）

### 6.1 两轮块匹配

1. **粗匹配**：复用 `md_diff_docx._block_key`，用 `SequenceMatcher` 得 `equal/delete/insert/replace` opcodes。
2. **replace 细化**：对每对 replace 块计算相似度 `ratio`：
   - `ratio >= 0.5` → 同一块被修改，进入 §6.2 分级
   - `ratio < 0.5` → 拆成 delete + insert

### 6.2 分级处理表

| baseline 块 | reviewed 块 | 条件 | 产出的 MdEdit |
|-------------|-------------|------|---------------|
| Paragraph | Paragraph | 文本不同 | `replacement=reviewed_text, reason='text_edit'` |
| Heading | Heading | 级别或文本不同 | 同上，保留 `#` 级别 |
| Equation | Equation | latex/OMML 指纹不同 | `replacement='<!-- REVIEW: formula changed, see attachments/{n}.png -->'`，副产物：渲染截图 |
| Table | Table | 同形状，单元格文本不同 | 每改动单元格一条 `text_edit`，按 `\| cell \|` 精确替换 |
| Table | Table | 形状变了 | `replacement=md_render(reviewed_block)`, `reason='table_restructured'` |
| Figure | Figure | alt/path/二进制不同 | 新图 sha256 存 `typora-user-images/img-<sha8>.png`，改 md 路径 |
| Code | Code | 代码不同 | 整块替换，`reason='code_edit'` |
| List | List | 条目增删改 | 对齐后逐条 / 整块替换 |
| * | None | 删除 | `replacement=''` |
| None | * | 新增 | `replacement=md_render(reviewed_block)`，插邻近 equal 块之后 |

**公式截图实现**：把 reviewed block 的 `<m:oMath>` 包进最小骨架 docx → `libreoffice --headless --convert-to png`。无 libreoffice 则降级为保存片段 docx 到 `review/attachments/<n>.docx`。

### 6.3 批注处理

```python
for comment in all_comments:
    cls = comment_classifier.classify(
        block_text=anchor_block.text,
        anchor_text=comment.anchor_text,
        comment_body=comment.text,
        md_context=前后 1-2 段,
    )
    if cls['kind'] == 'edit' and cls['confidence'] >= 0.7:
        edits.append(MdEdit(..., reason='comment_edit',
                           provenance=f'comment by {comment.author}: "{comment.text[:30]}..."'))
    else:
        edits.append(MdEdit(
            target_line_range=(anchor_line, anchor_line),   # 在该行末尾插入
            replacement=f'\n<!-- REVIEWER[{comment.author}]: {comment.text} -->',
            reason='comment_opinion',
            provenance=f'comment by {comment.author}',
        ))
```

置信度阈值 **0.7**；低于阈值一律当 opinion 处理。

### 6.4 应用 MdEdit

按 `target_line_range[0]` **倒序**应用（避免行号漂移）：

```python
edits.sort(key=lambda e: e.target_line_range[0], reverse=True)
lines = baseline_md_text.splitlines(keepends=True)
for e in edits:
    lines[e.target_line_range[0]:e.target_line_range[1]] = \
        [e.replacement + '\n'] if e.replacement else []
```

**行号冲突**：两条 edit 的 range 重叠 → 保留审校 docx 中后出现的那条，被覆盖的前者加入 commit message `WARNING` 段。

## 7. LLM 批注分类

### 7.1 API 契约

```python
# comment_classifier.py
MODEL = 'claude-sonnet-4-6'

def classify(
    block_text: str,
    anchor_text: str,
    comment_body: str,
    client: Anthropic,
    md_context: str,
) -> dict:
    """
    返回：{
        'kind': 'edit' | 'opinion',
        'new_text': Optional[str],
        'confidence': float,   # 0..1
        'reasoning': str,
    }
    """
```

### 7.2 Prompt（启用 prompt caching）

SYSTEM（被 `cache_control: ephemeral` 缓存，跨批注共享）：
```
你是中文技术书籍审校的辅助分类器。给定一条 Word 批注，判断它是"明确的文本修改指令"还是"意见/建议"。

判别规则：
- edit：批注使用祈使/命令式或直接给出替换文本（"改成 X"、"X→Y"、"删掉"、"这句应为: ..."）
- opinion：批注在提问、讨论、建议但未给出确定的替换文本

边界判定：信息不足以确定替换文本时，返回 kind='opinion'。绝不自行发明替换文本。

输出必须是 JSON：
{
  "kind": "edit" | "opinion",
  "new_text": string | null,
  "confidence": number,
  "reasoning": string
}
```

USER（每条批注独立）：
```
批注锚点选中原文："{anchor_text}"
批注正文："{comment_body}"
锚点所在段落：
{block_text}
上下文：
{md_context}
```

### 7.3 成本控制
- 并发度 1（一章几十条批注不是瓶颈）
- Prompt caching：SYSTEM 只付一次全价，后续 ~10% 成本
- 无 `ANTHROPIC_API_KEY` → 降级为全部 opinion，首次打印 warning（不报错）
- 单条调用/JSON 解析失败 → 当前 comment 当 opinion，commit message 记 warning，继续其余

## 8. git_review 分支与 commit

### 8.1 分支命名

```
review/<reviewer-slug>-<YYYYMMDD>[-<N>]
```
- `reviewer-slug`：`--reviewer` → `pypinyin.slugify`；fallback 到 docx 的 `<w:ins w:author>` 多数值
- 同一天同一人多次 import → 自动 `-2/-3/...` 递增（不复用分支）

### 8.2 Commit author/committer

```
GIT_AUTHOR_NAME    = 审校者姓名
GIT_AUTHOR_EMAIL   = <slug>@review.local
GIT_COMMITTER_NAME = md-docx-bridge
GIT_COMMITTER_EMAIL= bridge@review.local
```

### 8.3 Commit message 模板

```
review: {n_text_edits} 处文本修改 / {n_struct} 处结构改动 / {n_opinions} 条意见

来自 {reviewer} 的审校（docx: {docx_filename}）
基线 commit: {base_sha_7}
基线来源: {baseline_source}   # metadata | filename | sidecar | cli

变动明细：
- text_edit: 第 123-125 行   "前者...被..." → "前者...改为..."
- formula_changed: 第 340 行  见 review/attachments/1.png
- figure_replaced: 第 631 行  → typora-user-images/img-a1b2c3d4.png
- comment_edit: 第 88 行      "删去「因此」" (conf=0.86)
- comment_opinion: 第 215 行  张三: "这段可以更精简"
...

{warnings_section}

Co-Authored-By: md-docx-bridge <bridge@review.local>
```

### 8.4 不触 main 的保证
- `import-review` 不切换 HEAD（用 `git commit-tree` + `update-ref`）
- 工作区有未提交改动 → 拒绝并提示 stash/commit
- `export-review` 只读（`git show` 不动 ref）

## 9. 错误处理矩阵

| 错误 | 策略 | Exit code |
|------|------|-----------|
| docx 不是 zip / 损坏 | 打印"docx 格式错误" | 2 |
| docx 无 ins/del/comment | 打印"未检测到改动"，不 commit | 0 |
| 基线所有四级回退都失败 | 提示 `--base --path` | 1 |
| 基线 sha 存在但 SourcePath 不存在 | sha/path 不匹配提示 | 1 |
| 工作区脏 | 提示 stash/commit | 1 |
| libreoffice 缺失 | 公式截图降级为片段 docx | warning |
| `ANTHROPIC_API_KEY` 缺失 | 全部 opinion + 一次 warning | warning |
| 单条批注 API 失败 | 该条当 opinion + commit warning | warning |
| MdEdit 行号冲突 | 后者覆盖前者 + commit warning | warning |
| review 分支创建冲突 | 递增 -N 后缀（最多 99） | 3 若用尽 |
| git commit 失败 | 透传错误 | git's |

## 10. 测试

### 10.1 目录结构

```
tests/
├── fixtures/
│   ├── minimal.md / minimal_edited.md
│   ├── reviewed_tracked.docx / reviewed_plain.docx
│   ├── reviewed_comments.docx / reviewed_mixed.docx
│
├── test_md_core.py           # 回归（LaTeX / Block 解析）
├── test_docx_reader.py       # docx → Block IR
├── test_docx_to_md.py        # 分级策略（每种 block 类型一个用例）
├── test_git_review.py        # 走真实 git（tmp 仓库）
├── test_comment_classifier.py# mock Anthropic
├── test_roundtrip.py         # 端到端
└── conftest.py               # git fixture
```

### 10.2 测试约定
- 不 mock git / 文件系统（用 tmp 目录真实 init 仓库）
- Anthropic **必须** mock；`comment_classifier` 接受 `client: Anthropic` 注入
- 关键 fixtures 由人手工制作（在 Word 里开 track changes 改 minimal.md 的导出 docx）

### 10.3 Smoke 脚本（`tests/smoke.sh`）

手动或 CI 运行，作为最低可接受：
1. init 临时仓库 + 提交 minimal.md
2. 改 md 并 commit
3. `export-review HEAD` → 断言 custom.xml 含 SourceGitCommit
4. `import-review reviewed_tracked.docx --reviewer "测试员"` → 断言 review/ceshiyuan-* 分支创建且 author 正确

## 11. 依赖

```
python-docx>=1.2.0     # 已用
lxml>=4.9              # 已用
latex2mathml>=3.78     # 已用
anthropic>=0.40        # 新
pypinyin>=0.50         # 新（中文 → slug）
```

可选（运行时探测）：
- `libreoffice`（系统命令）—— 公式截图，无则降级
- `pillow` —— 若未来做截图合成

## 12. 使用示例

### 送审

```bash
# 以 HEAD 相对 HEAD~1 生成送审 docx
python cli.py export-review HEAD

# 任意 range
python cli.py export-review c269457..6f7da18

# 上次送审之后累积改动
python cli.py export-review --since-last-review
```

### 回灌

```bash
# 典型（基线从 docx 自动识别）
python cli.py import-review chapter3_6f7da18_reviewed.docx --reviewer "张三"

# 基线丢失的兜底
python cli.py import-review random_name.docx --base 6f7da18 --path chapter3_new.md --reviewer "张三"
```

### 合并

```bash
git log review/zhangsan-20260423
git diff main..review/zhangsan-20260423
git merge --no-ff review/zhangsan-20260423
```

## 13. 未来工作（不在本次范围）

- 方案 2：统一中立 IR 重构（任务 #9）
- OMML → LaTeX 反向转换（需要高质量 LaTeX 生成器）
- 多文件批量送审 / 全书级导出
- Web UI / 审校者门户
- 自动把批注的"新图片"上传到飞书 / OSS
