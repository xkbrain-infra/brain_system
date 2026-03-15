#!/usr/bin/env bash
#
# container_bootstrap.sh - 容器启动引导脚本
#
# 环境变量（从 global.env.yaml / .env 读取）：
#   DEPLOYMENT_NAME       - 部署名称
#   INSTANCE_ID           - 实例ID
#   CONTAINER_PREFIX      - 容器名前缀
#   IPC_AGENT_PREFIX      - IPC Agent 前缀
#   BRAIN_PATH            - Brain 根目录
#   SECRETS_ROOT          - Secrets 根目录
#   SSH_SECRETS_DIR       - SSH Secrets 目录
#   HOST_KEYS_DIR         - Host Keys 目录
#   AGENT_AUTH_ROOT       - Agent Auth 根目录
#   SSH_DIR               - 用户 SSH 目录
#

set -euo pipefail

# ============================================
# 配置加载（带默认值，向后兼容）
# ============================================

DEPLOYMENT_NAME="${DEPLOYMENT_NAME:-xk-agent-infra}"
INSTANCE_ID="${INSTANCE_ID:-}"
CONTAINER_PREFIX="${CONTAINER_PREFIX:-XKAgentInfra}"
IPC_AGENT_PREFIX="${IPC_AGENT_PREFIX:-agent-brain}"

BRAIN_ROOT="${BRAIN_PATH:-/xkagent_infra/brain}"
SECRETS_ROOT="${SECRETS_ROOT:-${BRAIN_ROOT}/secrets/system}"
SSH_DIR="${SSH_DIR:-/root/.ssh}"
AUTH_KEYS="${AUTH_KEYS:-${SSH_DIR}/authorized_keys}"
SECRET_SSH_DIR="${SECRET_SSH_DIR:-${SECRETS_ROOT}/ssh}"
HOST_KEY_DIR="${HOST_KEY_DIR:-${SECRET_SSH_DIR}/host_keys}"
AGENT_AUTH_ROOT="${AGENT_AUTH_ROOT:-${SECRETS_ROOT}/agents/auth}"

# 计算实际容器名
if [[ -n "$INSTANCE_ID" ]]; then
    CONTAINER_NAME="${CONTAINER_PREFIX}-${INSTANCE_ID}"
else
    CONTAINER_NAME="${CONTAINER_PREFIX}"
fi

log() {
  printf "[bootstrap] %s\n" "$*"
}

log_warn() {
  printf "[bootstrap][WARN] %s\n" "$*" >&2
}

log_info() {
  printf "[bootstrap][INFO] %s\n" "$*"
}

# 显示配置摘要
show_config() {
    log_info "configuration:"
    log_info "  DEPLOYMENT_NAME=$DEPLOYMENT_NAME"
    log_info "  INSTANCE_ID=$INSTANCE_ID"
    log_info "  CONTAINER_NAME=$CONTAINER_NAME"
    log_info "  IPC_AGENT_PREFIX=$IPC_AGENT_PREFIX"
    log_info "  SECRETS_ROOT=$SECRETS_ROOT"
}

# 首先初始化 secrets（首次启动时自动生成 key）
INIT_SECRETS_SCRIPT="${BRAIN_ROOT}/platform/docker/scripts/init-secrets.sh"
if [[ -x "$INIT_SECRETS_SCRIPT" ]]; then
    log "running init-secrets..."
    "$INIT_SECRETS_SCRIPT" || log_warn "init-secrets returned non-zero, continuing..."
else
    log_warn "init-secrets script not found or not executable: $INIT_SECRETS_SCRIPT"
fi

LOGIN_INIT_SCRIPT="${BRAIN_ROOT}/platform/docker/scripts/agent_login_init.sh"
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

ensure_login_hook_for_shell_rc() {
  local rc_file="$1"
  local marker_begin="# >>> XKAGENT_LOGIN_INIT_HOOK >>>"
  local marker_end="# <<< XKAGENT_LOGIN_INIT_HOOK <<<"

  touch "$rc_file"

  if grep -Fq "$marker_begin" "$rc_file"; then
    return 0
  fi

  cat >>"$rc_file" <<'HOOK'
# >>> XKAGENT_LOGIN_INIT_HOOK >>>
if [ -n "${SSH_CONNECTION:-}" ] && [ -t 1 ] && [ -z "${XKAGENT_LOGIN_INIT_RAN:-}" ]; then
  export XKAGENT_LOGIN_INIT_RAN=1
  if [ -x /xkagent_infra/brain/platform/docker/scripts/agent_login_init.sh ]; then
    /xkagent_infra/brain/platform/docker/scripts/agent_login_init.sh || true
  fi
fi
# <<< XKAGENT_LOGIN_INIT_HOOK <<<
HOOK

  log "installed login init hook in ${rc_file}"
}

ensure_login_init_hook() {
  ensure_login_hook_for_shell_rc /root/.bashrc
  ensure_login_hook_for_shell_rc /root/.zshrc
}

# ============================================
# 主流程
# ============================================

log "container bootstrap starting..."
show_config

MODE="${1:-all}"
case "$MODE" in
  --agent-auth-only)
    sync_agent_auth
    ;;
  --ensure-login-hook)
    ensure_login_init_hook
    ;;
  *)
    sync_host_keys
    sync_authorized_keys
    sync_agent_auth
    ensure_login_init_hook
    ;;
esac

log "container bootstrap completed"
