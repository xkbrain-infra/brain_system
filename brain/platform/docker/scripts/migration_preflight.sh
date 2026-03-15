#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
CLI_INFRA_ROOT_HOST_PATH="${INFRA_ROOT_HOST_PATH-}"
CLI_SSH_PORT="${SSH_PORT-}"
CLI_DOCKER_DATA_ROOT_PATH="${DOCKER_DATA_ROOT_PATH-}"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck source=/dev/null
  set -a && source "$ENV_FILE" && set +a
fi

: "${INFRA_ROOT_HOST_PATH:=/services/xkagent_infra}"
: "${SSH_PORT:=8622}"
: "${DOCKER_DATA_ROOT_PATH:=./docker-data/root}"

if [[ -n "${CLI_INFRA_ROOT_HOST_PATH}" ]]; then
  INFRA_ROOT_HOST_PATH="${CLI_INFRA_ROOT_HOST_PATH}"
fi
if [[ -n "${CLI_SSH_PORT}" ]]; then
  SSH_PORT="${CLI_SSH_PORT}"
fi
if [[ -n "${CLI_DOCKER_DATA_ROOT_PATH}" ]]; then
  DOCKER_DATA_ROOT_PATH="${CLI_DOCKER_DATA_ROOT_PATH}"
fi

if [[ "$DOCKER_DATA_ROOT_PATH" = /* ]]; then
  DOCKER_DATA_ROOT_ABS="$DOCKER_DATA_ROOT_PATH"
else
  DOCKER_DATA_ROOT_ABS="${ROOT_DIR}/${DOCKER_DATA_ROOT_PATH}"
fi

echo "[INFO] preflight root=${INFRA_ROOT_HOST_PATH} ssh_port=${SSH_PORT} docker_data_root=${DOCKER_DATA_ROOT_ABS}"

for cmd in docker awk sed; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[ERROR] missing command: $cmd" >&2
    exit 1
  fi
done

if ! docker info >/dev/null 2>&1; then
  echo "[ERROR] docker daemon not reachable" >&2
  exit 1
fi

for d in \
  "$INFRA_ROOT_HOST_PATH" \
  "$INFRA_ROOT_HOST_PATH/brain" \
  "$INFRA_ROOT_HOST_PATH/groups" \
  "$INFRA_ROOT_HOST_PATH/tmp" \
  "$INFRA_ROOT_HOST_PATH/brain/platform" \
  "$INFRA_ROOT_HOST_PATH/runtime" \
  "$INFRA_ROOT_HOST_PATH/brain/secrets" \
  "$INFRA_ROOT_HOST_PATH/brain/infrastructure/config/agentctl"; do
  if [[ ! -d "$d" ]]; then
    echo "[ERROR] missing dir: $d" >&2
    exit 1
  fi
done

if [[ ! -d "$DOCKER_DATA_ROOT_ABS" ]]; then
  echo "[ERROR] missing dir: $DOCKER_DATA_ROOT_ABS" >&2
  exit 1
fi

RUNTIME_GUARD="$INFRA_ROOT_HOST_PATH/brain/bin/runtime_path_guard"
if [[ ! -x "$RUNTIME_GUARD" ]]; then
  echo "[ERROR] missing executable: $RUNTIME_GUARD" >&2
  exit 1
fi

if ! "$RUNTIME_GUARD" --root "$INFRA_ROOT_HOST_PATH" --check-filesystem; then
  echo "[ERROR] runtime path guard failed" >&2
  exit 1
fi

if ! docker compose --env-file "$ENV_FILE" -f "${ROOT_DIR}/compose.yaml" config >/dev/null 2>&1; then
  echo "[ERROR] compose render failed" >&2
  exit 1
fi

echo "[OK] preflight passed"
