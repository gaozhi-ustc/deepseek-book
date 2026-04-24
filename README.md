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

## 安装 Codex skill

本仓库包含打包好的 Codex skill：`skills/md-docx-review-bridge.tgz`。
在其他设备 clone 本项目后运行：

```bash
bash scripts/install-md-docx-review-bridge-skill.sh
```

默认安装到 `${CODEX_HOME:-$HOME/.codex}/skills/md-docx-review-bridge`。
如目标目录已存在，用下面命令覆盖：

```bash
bash scripts/install-md-docx-review-bridge-skill.sh --force
```

安装后重启 Codex，让新 skill 生效。该 skill 负责指导 agent 使用本项目的
`export-review` / `import-review` 审校桥流程。

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

产出 `review/zhangsan-20260424[-N]` 分支上的一个 commit，author 为审校者，committer 为 `md-docx-bridge`。**HEAD 不动，main 工作区不动。**

### 合并 review 分支（手动）

```bash
git log review/zhangsan-20260424
git diff main..review/zhangsan-20260424
git merge --no-ff review/zhangsan-20260424
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
