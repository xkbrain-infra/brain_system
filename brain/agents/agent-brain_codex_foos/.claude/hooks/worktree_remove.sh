#!/usr/bin/env bash
set -euo pipefail

INPUT="$(cat)"
WORKTREE_PATH="$(printf '%s' "$INPUT" | jq -r '.worktree_path')"

if [[ -z "$WORKTREE_PATH" || "$WORKTREE_PATH" == "null" ]]; then
  exit 0
fi

REPO_ROOT="$(git -C "$WORKTREE_PATH" rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -n "$REPO_ROOT" ]]; then
  git -C "$REPO_ROOT" worktree remove --force "$WORKTREE_PATH" >/dev/null 2>&1 || rm -rf "$WORKTREE_PATH"
else
  rm -rf "$WORKTREE_PATH"
fi
