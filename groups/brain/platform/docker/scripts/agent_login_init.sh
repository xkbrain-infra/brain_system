#!/usr/bin/env bash
set -euo pipefail

log() {
  printf "[agent-init] %s\n" "$*"
}

ROOT_DIR="/xkagent_infra/brain"
BOOTSTRAP_SCRIPT="${ROOT_DIR}/platform/docker/scripts/container_bootstrap.sh"
AGENTCTL="${ROOT_DIR}/infrastructure/service/agentctl/bin/agentctl"
SETUP_GUIDE="${ROOT_DIR}/secrets/system/agents/auth/SETUP_GUIDE.md"
AUTH_MANAGER_BIN="${ROOT_DIR}/infrastructure/service/brain_auth_manager/bin/brain_auth_manager"

MARKER_DIR="/root/.xkagent"
MARKER_FILE="${MARKER_DIR}/agent_init.done"
LOG_FILE="${MARKER_DIR}/agent_init.last.log"

FORCE=0
if [[ "${1:-}" == "--force" ]]; then
  FORCE=1
fi

AUTOSTART_RAW="${AGENTCTL_AUTOSTART_AGENTS:-agent-brain_manager}"
AUTOSTART_RAW="${AUTOSTART_RAW//,/ }"
read -r -a AUTOSTART_TARGETS <<<"$AUTOSTART_RAW"

mkdir -p "$MARKER_DIR"

if [[ "$FORCE" -eq 0 && -f "$MARKER_FILE" ]]; then
  DONE_AT="$(cat "$MARKER_FILE" 2>/dev/null || true)"
  log "already initialized (${DONE_AT:-unknown-time})"
  log "run '${BOOTSTRAP_SCRIPT}' to re-sync auth files"
  log "run '${ROOT_DIR}/platform/docker/scripts/agent_login_init.sh --force' to re-run full init"
  exit 0
fi

# Persist console output for troubleshooting.
# Keep TTY untouched in interactive sessions, otherwise OAuth/device flows may appear frozen.
if [[ -t 1 ]]; then
  :
else
  exec > >(tee "$LOG_FILE") 2>&1
fi

log "starting first-login initialization"
log "time: $(date -Iseconds)"

FAIL=0
MISSING=0
CLAUDE_MISSING=0
CODEX_MISSING=0
GEMINI_MISSING=0

PYTHON_BIN=""
if [[ -x /opt/venv/bin/python3 ]]; then
  PYTHON_BIN="/opt/venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  log "python3 not found"
  FAIL=1
fi

if [[ -n "$PYTHON_BIN" ]]; then
  if ! "$PYTHON_BIN" - <<'PY'
import yaml
PY
  then
    log "python missing PyYAML: ${PYTHON_BIN}"
    log "fix: use /opt/venv/bin/python3 or install pyyaml in active python"
    FAIL=1
  fi
fi

run_step() {
  local name="$1"
  shift
  log "step: ${name}"
  if "$@"; then
    log "ok: ${name}"
  else
    log "failed: ${name}"
    FAIL=1
  fi
}

check_auth_file() {
  local path="$1"
  if [[ -f "$path" ]]; then
    printf "  [ok] %s\n" "$path"
    return 0
  fi
  printf "  [missing] %s\n" "$path"
  return 1
}

show_auth_status() {
  local title="$1"
  echo "[agent-init] ${title}"

  MISSING=0
  CLAUDE_MISSING=0
  CODEX_MISSING=0
  GEMINI_MISSING=0

  if ! check_auth_file /root/.claude.json; then
    MISSING=1
    CLAUDE_MISSING=1
  fi

  if ! check_auth_file /root/.codex/auth.json; then
    MISSING=1
    CODEX_MISSING=1
  fi

  local gemini_local_missing=0
  if ! check_auth_file /root/.gemini/oauth_creds.json; then gemini_local_missing=1; fi
  if ! check_auth_file /root/.gemini/google_accounts.json; then gemini_local_missing=1; fi
  if ! check_auth_file /root/.gemini/installation_id; then gemini_local_missing=1; fi
  if ! check_auth_file /root/.gemini/state.json; then gemini_local_missing=1; fi
  if [[ "$gemini_local_missing" -eq 1 ]]; then
    MISSING=1
    GEMINI_MISSING=1
  fi
}

find_auth_manager() {
  if [[ -x "$AUTH_MANAGER_BIN" ]]; then
    return 0
  fi
  if command -v brain_auth_manager >/dev/null 2>&1; then
    AUTH_MANAGER_BIN="$(command -v brain_auth_manager)"
    return 0
  fi
  return 1
}

ask_yes_no() {
  local prompt="$1"
  local default_yes="$2"
  local reply=""

  if [[ "$default_yes" -eq 1 ]]; then
    read -r -p "$prompt [Y/n]: " reply || true
    reply="${reply:-Y}"
  else
    read -r -p "$prompt [y/N]: " reply || true
    reply="${reply:-N}"
  fi

  case "${reply}" in
    y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

run_interactive_auth_wizard() {
  local selected=()

  log "auth guide: missing agents detected"
  [[ "$CLAUDE_MISSING" -eq 1 ]] && log "  - claude"
  [[ "$CODEX_MISSING" -eq 1 ]] && log "  - codex"
  [[ "$GEMINI_MISSING" -eq 1 ]] && log "  - gemini"

  if ! ask_yes_no "start auth wizard now?" 1; then
    log "auth guide skipped by user"
    return 1
  fi

  if [[ "$CLAUDE_MISSING" -eq 1 ]] && ask_yes_no "authorize claude now?" 1; then
    selected+=("claude")
  fi
  if [[ "$CODEX_MISSING" -eq 1 ]] && ask_yes_no "authorize codex now?" 1; then
    selected+=("codex")
  fi
  if [[ "$GEMINI_MISSING" -eq 1 ]] && ask_yes_no "authorize gemini now?" 1; then
    selected+=("gemini")
  fi

  if [[ "${#selected[@]}" -eq 0 ]]; then
    log "no agents selected in wizard"
    return 1
  fi

  for agent in "${selected[@]}"; do
    log "auth guide: next agent=${agent}"
    log "auth guide: complete browser/device verification, then return to this terminal"
    if ! "$AUTH_MANAGER_BIN" --brain-root "$ROOT_DIR" guide --agents "$agent" --yes --sync-to-secrets; then
      log "auth guide: ${agent} failed"
    fi
  done

  return 0
}

run_step "sync auth files from secrets" "$BOOTSTRAP_SCRIPT" --agent-auth-only
show_auth_status "auth status:"

if [[ "$MISSING" -eq 1 ]]; then
  log "some auth files are missing"

  if [[ -t 0 ]] && find_auth_manager; then
    log "step: interactive auth guide"
    if run_interactive_auth_wizard; then
      log "ok: interactive auth guide"
    else
      log "failed: interactive auth guide"
    fi
    show_auth_status "auth status (after guide):"
  elif [[ ! -t 0 ]]; then
    log "non-interactive session detected; skip interactive auth guide"
  else
    log "brain_auth_manager not found; skip interactive auth guide"
  fi

  if [[ "$MISSING" -eq 1 ]]; then
    log "put auth files under: ${ROOT_DIR}/secrets/system/agents/auth"
    log "see guide: ${SETUP_GUIDE}"
    log "or authenticate interactively in this SSH session:"
    log "  - Claude: claude auth login"
    log "  - Codex:  codex login --device-auth   (or: printenv OPENAI_API_KEY | codex login --with-api-key)"
    log "  - Gemini: run 'gemini' once and complete web/device login flow"
    FAIL=1
  fi
fi

if [[ -n "$PYTHON_BIN" ]]; then
  if [[ "${#AUTOSTART_TARGETS[@]}" -gt 0 ]]; then
    run_step "apply autostart agent configs" "$PYTHON_BIN" "$AGENTCTL" apply-config "${AUTOSTART_TARGETS[@]}" --apply --force
    run_step "start autostart agents" "$PYTHON_BIN" "$AGENTCTL" start "${AUTOSTART_TARGETS[@]}" --apply --force
  else
    log "skip autostart: AGENTCTL_AUTOSTART_AGENTS is empty"
  fi
  run_step "show agent list" "$PYTHON_BIN" "$AGENTCTL" list
  run_step "show online agents" "$PYTHON_BIN" "$AGENTCTL" online
else
  log "skip agentctl steps: python unavailable"
  FAIL=1
fi

if [[ "$FAIL" -eq 0 ]]; then
  date -Iseconds > "$MARKER_FILE"
  chmod 600 "$MARKER_FILE" || true
  log "initialization completed successfully"
  exit 0
fi

rm -f "$MARKER_FILE"
log "initialization incomplete; fix issues and re-login, or run --force after fixing"
exit 0
