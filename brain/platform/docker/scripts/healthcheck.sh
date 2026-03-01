#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-runtime}"

log() {
  printf '[healthcheck] %s\n' "$*"
}

fail() {
  printf '[healthcheck][ERROR] %s\n' "$*" >&2
  exit 1
}

require_path() {
  local p="$1"
  [[ -e "$p" ]] || fail "missing path: $p"
}

require_dir() {
  local p="$1"
  [[ -d "$p" ]] || fail "missing dir: $p"
}

require_cmd() {
  local c="$1"
  command -v "$c" >/dev/null 2>&1 || fail "missing command: $c"
}

check_init() {
  require_dir /xkagent_infra/brain
  require_dir /xkagent_infra/groups
  require_dir /xkagent_infra/brain/infrastructure/config/agentctl
  require_dir /xkagent_infra/brain/runtime
  require_path /xkagent_infra/brain/infrastructure/service/brain_ipc/bin/current/brain_ipc
  require_path /xkagent_infra/brain/infrastructure/service/agentctl/bin/brain-agentctl
  require_path /etc/supervisor/conf.d/supervisord.conf
  log "init checks passed"
}

check_runtime() {
  require_cmd supervisorctl
  require_cmd python3
  require_cmd tmux

  local status
  status="$(supervisorctl status || true)"
  [[ "$status" == *"sshd                             RUNNING"* ]] || fail "sshd not running"
  [[ "$status" == *"brain_ipc                        RUNNING"* ]] || fail "brain_ipc not running"
  [[ "$status" == *"agent_orchestrator               RUNNING"* ]] || fail "agent_orchestrator not running"

  local agentctl="python3 /xkagent_infra/brain/infrastructure/service/agentctl/bin/brain-agentctl"
  local online
  online="$(AGENTCTL_CONFIG_DIR=/xkagent_infra/brain/infrastructure/config/agentctl bash -lc "$agentctl online" || true)"
  [[ "$online" != *"daemon: unavailable"* ]] || fail "IPC daemon unavailable"

  # Optional strict mode: require resident agents to keep tmux sessions alive.
  # Default off because first-run interactive prompts can temporarily terminate sessions.
  if [[ "${REQUIRE_RESIDENT_AGENTS:-0}" == "1" ]]; then
    local list_out
    list_out="$(AGENTCTL_CONFIG_DIR=/xkagent_infra/brain/infrastructure/config/agentctl bash -lc "$agentctl list" || true)"
    local required_agents=(
      "agent-brain_manager"
      "agent-system_devops"
      "agent-system_pmo"
    )
    local a
    for a in "${required_agents[@]}"; do
      grep -Eq "^${a}[[:space:]]+running\\b" <<<"$list_out" || fail "agent not running: $a"
    done
  fi
  log "runtime checks passed"
}

case "$MODE" in
  init)
    check_init
    ;;
  runtime|startup)
    check_init
    check_runtime
    ;;
  *)
    fail "unknown mode: $MODE (expected: init|runtime|startup)"
    ;;
esac
