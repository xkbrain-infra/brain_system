#!/usr/bin/env bash
set -euo pipefail

INPUT="$(cat)"
NAME="$(printf '%s' "$INPUT" | jq -r '.name')"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPO_ROOT="$(git -C "$PROJECT_DIR" rev-parse --show-toplevel)"
WORKTREE_PATH="$REPO_ROOT/.claude/worktrees/$NAME"

if [[ -d "$WORKTREE_PATH" ]]; then
  git -C "$REPO_ROOT" worktree remove --force "$WORKTREE_PATH" >/dev/null 2>&1 || rm -rf "$WORKTREE_PATH"
fi

mkdir -p "$(dirname "$WORKTREE_PATH")"
git -C "$REPO_ROOT" worktree add --detach "$WORKTREE_PATH" HEAD >&2

mkdir -p "$WORKTREE_PATH/.claude"
cp "$PROJECT_DIR/.claude/settings.local.json" "$WORKTREE_PATH/.claude/settings.local.json"

if [[ -d "$PROJECT_DIR/.claude/hooks" ]]; then
  mkdir -p "$WORKTREE_PATH/.claude/hooks"
  cp "$PROJECT_DIR/.claude/hooks/"*.sh "$WORKTREE_PATH/.claude/hooks/" 2>/dev/null || true
fi

printf '%s\n' "$WORKTREE_PATH"
