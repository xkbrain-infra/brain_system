#!/usr/bin/env bash
set -euo pipefail

log() {
  printf "[bootstrap] %s\n" "$*"
}

SSH_DIR="/root/.ssh"
AUTH_KEYS="${SSH_DIR}/authorized_keys"
SECRET_SSH_DIR="${SECRET_SSH_DIR:-/xkagent_infra/brain/secrets/system/ssh}"
HOST_KEY_DIR="${HOST_KEY_DIR:-${SECRET_SSH_DIR}/host_keys}"
AGENT_AUTH_ROOT="${AGENT_AUTH_ROOT:-/xkagent_infra/brain/secrets/system/agents/auth}"
TMP_KEYS="$(mktemp)"
trap "rm -f \"$TMP_KEYS\"" EXIT

append_keys_from_file() {
  local f="$1"
  [[ -f "$f" ]] || return 0
  # Keep only valid OpenSSH public key lines.
  grep -E "^(ssh-(rsa|ed25519)|ecdsa-sha2-nistp(256|384|521))[[:space:]]+[A-Za-z0-9+/=]+([[:space:]].*)?$" "$f" >>"$TMP_KEYS" || true
}

sync_host_keys() {
  mkdir -p "$HOST_KEY_DIR"
  chmod 700 "$HOST_KEY_DIR" || true

  local found=0
  local f

  shopt -s nullglob
  for f in "$HOST_KEY_DIR"/ssh_host_*_key; do
    [[ -f "$f" ]] || continue
    found=1
    cp -f "$f" "/etc/ssh/$(basename "$f")"
    chmod 600 "/etc/ssh/$(basename "$f")" || true
    if [[ -f "${f}.pub" ]]; then
      cp -f "${f}.pub" "/etc/ssh/$(basename "${f}.pub")"
      chmod 644 "/etc/ssh/$(basename "${f}.pub")" || true
    fi
  done
  shopt -u nullglob

  if [[ "$found" -eq 1 ]]; then
    log "loaded persistent SSH host keys from ${HOST_KEY_DIR}"
    return 0
  fi

  if ! ls /etc/ssh/ssh_host_*_key >/dev/null 2>&1; then
    ssh-keygen -A >/dev/null 2>&1 || true
  fi

  shopt -s nullglob
  for f in /etc/ssh/ssh_host_*_key; do
    [[ -f "$f" ]] || continue
    cp -f "$f" "$HOST_KEY_DIR/$(basename "$f")"
    chmod 600 "$HOST_KEY_DIR/$(basename "$f")" || true
    if [[ -f "${f}.pub" ]]; then
      cp -f "${f}.pub" "$HOST_KEY_DIR/$(basename "${f}.pub")"
      chmod 644 "$HOST_KEY_DIR/$(basename "${f}.pub")" || true
    fi
  done
  shopt -u nullglob

  log "initialized persistent SSH host keys in ${HOST_KEY_DIR}"
}

sync_authorized_keys() {
  mkdir -p "$SSH_DIR"
  chmod 700 "$SSH_DIR"

  # Existing keys remain valid baseline.
  append_keys_from_file "$AUTH_KEYS"

  # Preferred explicit file.
  append_keys_from_file "${SECRET_SSH_DIR}/authorized_keys"
  append_keys_from_file "${SECRET_SSH_DIR}/authorized_keys.pub"

  # Any *.pub dropped in secret dir.
  if [[ -d "$SECRET_SSH_DIR" ]]; then
    local f
    for f in "$SECRET_SSH_DIR"/*.pub; do
      [[ -f "$f" ]] || continue
      append_keys_from_file "$f"
    done
  fi

  if [[ -s "$TMP_KEYS" ]]; then
    sort -u "$TMP_KEYS" >"$AUTH_KEYS"
    chmod 600 "$AUTH_KEYS"
    log "authorized_keys synced from ${SECRET_SSH_DIR}"
  else
    log "no SSH public keys found in ${SECRET_SSH_DIR}; keeping current authorized_keys state"
  fi
}

sync_auth_file() {
  local src="$1"
  local dest="$2"
  local mode="$3"

  [[ -f "$src" ]] || return 0

  mkdir -p "$(dirname "$dest")"
  cp -f "$src" "$dest"
  chmod "$mode" "$dest" || true
  log "synced auth file: ${src} -> ${dest}"
}

sync_agent_auth() {
  if [[ ! -d "$AGENT_AUTH_ROOT" ]]; then
    log "agent auth directory not found: ${AGENT_AUTH_ROOT} (skip)"
    return 0
  fi

  # Claude Code login/session
  sync_auth_file "${AGENT_AUTH_ROOT}/claude/.claude.json" "/root/.claude.json" 600

  # Codex login token/cache
  sync_auth_file "${AGENT_AUTH_ROOT}/codex/auth.json" "/root/.codex/auth.json" 600

  # Gemini CLI login/session
  sync_auth_file "${AGENT_AUTH_ROOT}/gemini/oauth_creds.json" "/root/.gemini/oauth_creds.json" 600
  sync_auth_file "${AGENT_AUTH_ROOT}/gemini/google_accounts.json" "/root/.gemini/google_accounts.json" 600
  sync_auth_file "${AGENT_AUTH_ROOT}/gemini/installation_id" "/root/.gemini/installation_id" 600
  sync_auth_file "${AGENT_AUTH_ROOT}/gemini/state.json" "/root/.gemini/state.json" 600
}

cleanup_login_hook_from_shell_rc() {
  local rc_file="$1"
  local marker_begin="# >>> XKAGENT_LOGIN_INIT_HOOK >>>"
  local marker_end="# <<< XKAGENT_LOGIN_INIT_HOOK <<<"
  local tmp_file

  [[ -f "$rc_file" ]] || return 0

  if ! grep -Fq "$marker_begin" "$rc_file"; then
    return 0
  fi

  tmp_file="$(mktemp)"
  awk -v begin="$marker_begin" -v end="$marker_end" '
    $0 == begin { skip=1; next }
    $0 == end { skip=0; next }
    !skip { print }
  ' "$rc_file" >"$tmp_file"
  mv "$tmp_file" "$rc_file"
  log "removed login init hook from ${rc_file}"
}

cleanup_login_init_hook() {
  cleanup_login_hook_from_shell_rc /root/.bashrc
  cleanup_login_hook_from_shell_rc /root/.zshrc
}

MODE="${1:-all}"
case "$MODE" in
  --agent-auth-only)
    sync_agent_auth
    ;;
  --ensure-login-hook)
    cleanup_login_init_hook
    ;;
  *)
    sync_host_keys
    sync_authorized_keys
    sync_agent_auth
    cleanup_login_init_hook
    ;;
esac
