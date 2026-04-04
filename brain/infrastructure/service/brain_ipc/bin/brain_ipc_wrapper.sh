#!/usr/bin/env bash
set -euo pipefail

REAL_BIN="/xkagent_infra/brain/infrastructure/service/brain_ipc/bin/brain_ipc.bin"
CANONICAL_SOCKET="/tmp/brain_ipc.sock"
REDIRECT_SOCKET="/brain/tmp_ipc/brain_ipc.sock"

cleanup() {
  if [[ -n "${helper_pid:-}" ]]; then
    kill "$helper_pid" 2>/dev/null || true
    wait "$helper_pid" 2>/dev/null || true
  fi
}

trap cleanup EXIT

"$REAL_BIN" "$@" &
child_pid=$!

(
  while kill -0 "$child_pid" 2>/dev/null; do
    if [[ -S "$REDIRECT_SOCKET" ]]; then
      if [[ -L "$CANONICAL_SOCKET" && "$(readlink "$CANONICAL_SOCKET")" != "$REDIRECT_SOCKET" ]]; then
        rm -f "$CANONICAL_SOCKET"
      fi
      if [[ ! -e "$CANONICAL_SOCKET" ]]; then
        ln -s "$REDIRECT_SOCKET" "$CANONICAL_SOCKET" 2>/dev/null || true
      fi
    fi
    sleep 1
  done
) &
helper_pid=$!

wait "$child_pid"
exit $?
