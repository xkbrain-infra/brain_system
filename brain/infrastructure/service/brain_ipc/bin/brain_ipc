#!/usr/bin/env bash
set -euo pipefail

REAL_BIN="/xkagent_infra/brain/infrastructure/service/brain_ipc/bin/brain_ipc.bin"
CANONICAL_SOCKET="/tmp/brain_ipc.sock"
REDIRECT_SOCKET="/brain/tmp_ipc/brain_ipc.sock"

ensure_redirect_socket() {
  local redirect_dir
  redirect_dir="$(dirname "$REDIRECT_SOCKET")"
  mkdir -p "$redirect_dir"

  if [[ -L "$REDIRECT_SOCKET" ]]; then
    if [[ "$(readlink "$REDIRECT_SOCKET")" != "$CANONICAL_SOCKET" ]]; then
      rm -f "$REDIRECT_SOCKET"
    else
      return 0
    fi
  fi

  if [[ -e "$REDIRECT_SOCKET" ]]; then
    return 0
  fi

  ln -s "$CANONICAL_SOCKET" "$REDIRECT_SOCKET"
}

ensure_redirect_socket
exec "$REAL_BIN" "$@"
