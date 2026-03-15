#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
CONTAINER_NAME="${CONTAINER_NAME:-XKAgentInfra}"
MAX_WAIT_SECONDS="${MAX_WAIT_SECONDS:-180}"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck source=/dev/null
  set -a && source "$ENV_FILE" && set +a
fi

bash "${ROOT_DIR}/scripts/migration_preflight.sh"

docker compose --env-file "$ENV_FILE" -f "${ROOT_DIR}/compose.yaml" up -d --build --force-recreate

echo "[INFO] waiting for ${CONTAINER_NAME} health status (timeout=${MAX_WAIT_SECONDS}s)"
elapsed=0
while (( elapsed < MAX_WAIT_SECONDS )); do
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${CONTAINER_NAME}" 2>/dev/null || echo "missing")"
  if [[ "$health" == "healthy" ]]; then
    echo "[OK] ${CONTAINER_NAME} is healthy"
    exit 0
  fi
  if [[ "$health" == "unhealthy" || "$health" == "missing" ]]; then
    echo "[ERROR] ${CONTAINER_NAME} health=${health}" >&2
    docker ps --filter "name=^/${CONTAINER_NAME}$" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' || true
    exit 1
  fi
  sleep 3
  elapsed=$((elapsed + 3))
done

echo "[ERROR] ${CONTAINER_NAME} health check timed out after ${MAX_WAIT_SECONDS}s" >&2
docker ps --filter "name=^/${CONTAINER_NAME}$" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' || true
exit 1

