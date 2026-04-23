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

echo "== smoke: 构造有实质改动的审校 docx（绕开 export-review 的 no-op）"
# export-review 产出的 docx 接受所有修订后 == HEAD，import 是 no-op。
# smoke 重点验证 import-review 的分支建立链路，所以用 build_min_docx 造一份真改过的。
REVIEWED_DOCX="$TMP/reviewed.docx"
python3.14 - <<PY
import sys; sys.path.insert(0, "$ROOT")
from tests.fixtures.build_min_docx import write_docx, make_paragraph, make_heading
body = '\n'.join([
    make_heading(1, '第 1 章  测试章节'),
    make_heading(2, '1.1 第一节（审校加了一句）'),
    make_paragraph('这是第一段内容，用来测试 track changes。审校者在这里补了一句。'),
])
write_docx("$REVIEWED_DOCX", body)

from git_review import stamp_docx_metadata
stamp_docx_metadata("$REVIEWED_DOCX", "$HEAD_SHA", "$HEAD_SHA", "chapter.md", "2026-04-24T00:00:00Z")
PY

echo "== smoke: import-review $REVIEWED_DOCX --reviewer 测试员"
HEAD_BEFORE=$(git -C "$TMP" rev-parse HEAD)
( cd "$TMP" && python3.14 "$ROOT/cli.py" import-review "$REVIEWED_DOCX" --reviewer 测试员 )

# HEAD 未被切走
HEAD_AFTER=$(git -C "$TMP" rev-parse HEAD)
[ "$HEAD_BEFORE" = "$HEAD_AFTER" ] || { echo "FAIL: HEAD 被改动 $HEAD_BEFORE → $HEAD_AFTER"; exit 1; }

# 找 review 分支
BRANCH=$(git -C "$TMP" for-each-ref --format='%(refname:short)' refs/heads/review/ceshiyuan-\* | head -n1)
[ -n "$BRANCH" ] || { echo "FAIL: 未找到 review/ceshiyuan-* 分支"; exit 1; }

# 验证 author
AUTHOR=$(git -C "$TMP" log -1 --pretty='%an' "$BRANCH")
[ "$AUTHOR" = "测试员" ] || { echo "FAIL: author=$AUTHOR, 期望 测试员"; exit 1; }

# 验证 committer
CN=$(git -C "$TMP" log -1 --pretty='%cn' "$BRANCH")
[ "$CN" = "md-docx-bridge" ] || { echo "FAIL: committer=$CN"; exit 1; }

echo "== smoke: PASS"
