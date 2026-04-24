#!/usr/bin/env bash
# Install the bundled md-docx-review-bridge Codex skill.

set -euo pipefail
export LANG=C
export LC_ALL=C

SKILL_NAME="md-docx-review-bridge"
FORCE=0
ARCHIVE_PATH=""

usage() {
  cat <<'USAGE'
Usage: scripts/install-md-docx-review-bridge-skill.sh [--force] [--archive PATH]

Installs the bundled md-docx-review-bridge skill into:
  ${CODEX_HOME:-$HOME/.codex}/skills/md-docx-review-bridge

Options:
  --force         Replace an existing installed skill directory.
  --archive PATH  Install from a specific .tgz archive.
  -h, --help      Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force)
      FORCE=1
      shift
      ;;
    --archive)
      if [[ $# -lt 2 ]]; then
        echo "error: --archive requires a path" >&2
        exit 2
      fi
      ARCHIVE_PATH="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ARCHIVE_PATH="${ARCHIVE_PATH:-$PROJECT_ROOT/skills/$SKILL_NAME.tgz}"
DEST_ROOT="${CODEX_HOME:-$HOME/.codex}/skills"
DEST_DIR="$DEST_ROOT/$SKILL_NAME"

if [[ ! -f "$ARCHIVE_PATH" ]]; then
  echo "error: archive not found: $ARCHIVE_PATH" >&2
  exit 1
fi

if [[ -e "$DEST_DIR" ]]; then
  if [[ "$FORCE" -ne 1 ]]; then
    echo "error: $DEST_DIR already exists; rerun with --force to replace it" >&2
    exit 1
  fi
  rm -rf "$DEST_DIR"
fi

mkdir -p "$DEST_ROOT"
tar -xzf "$ARCHIVE_PATH" -C "$DEST_ROOT"

if [[ ! -f "$DEST_DIR/SKILL.md" ]]; then
  echo "error: archive did not install $DEST_DIR/SKILL.md" >&2
  exit 1
fi

echo "Installed $SKILL_NAME to $DEST_DIR"
echo "Restart Codex to pick up new skills."
