#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TM_BIN="${ROOT_DIR}/build/service-task_manager"
if [[ ! -x "${TM_BIN}" ]]; then
  TM_BIN="${ROOT_DIR}/bin/current/service-task_manager"
fi
IPC_BIN="${ROOT_DIR}/tests/bin/brain_ipc"
if [[ ! -x "${IPC_BIN}" ]]; then
  IPC_BIN="/brain/infrastructure/service/brain_ipc/releases/v1.0.0/bin/brain_ipc"
fi
SOCKET_PATH="/tmp/brain_ipc.sock"

if [[ ! -x "${TM_BIN}" ]]; then
  echo "[FAIL] service-task_manager binary not found"
  exit 1
fi
if [[ ! -x "${IPC_BIN}" ]]; then
  echo "[FAIL] brain_ipc binary not found: ${IPC_BIN}"
  exit 1
fi

TMP_DIR="$(mktemp -d /tmp/tm-smoke-test.XXXXXX)"
CFG_PATH="${TMP_DIR}/task_manager.yaml"
LOG_PATH="${TMP_DIR}/task_manager.log"
DATA_DIR="${TMP_DIR}/data"
mkdir -p "${DATA_DIR}"

SERVICE_NAME="service-task_manager_smoke_$$"
REQUESTER="agent_smoke_client_$$"
OWNER="agent_smoke_owner_$$"
SPEC_ID="SMOKE-$$"
GROUP_NAME="system"
SPEC_DIR="/brain/groups/org/${GROUP_NAME}/spec/${SPEC_ID}"

started_daemon=0

cleanup() {
  if [[ -n "${TM_PID:-}" ]] && kill -0 "${TM_PID}" 2>/dev/null; then
    kill -TERM "${TM_PID}" 2>/dev/null || true
    wait "${TM_PID}" 2>/dev/null || true
  fi
  if [[ "${started_daemon}" -eq 1 ]]; then
    "${IPC_BIN}" stop >/dev/null 2>&1 || true
    wait "${IPC_PID:-0}" 2>/dev/null || true
  fi
  rm -rf "${TMP_DIR}" "${SPEC_DIR}"
}
trap cleanup EXIT

ipc_ping() {
  python3 - <<'PY'
import json, socket, sys
sock="/tmp/brain_ipc.sock"
try:
    s=socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(0.8)
    s.connect(sock)
    s.sendall(b'{"action":"ping","data":{}}\n')
    buf=b""
    while True:
        c=s.recv(4096)
        if not c:
            break
        buf += c
        if b"\n" in buf:
            break
    s.close()
    obj=json.loads(buf.decode("utf-8"))
    sys.exit(0 if obj.get("status") in ("ok","pong") else 1)
except Exception:
    sys.exit(1)
PY
}

if ! ipc_ping; then
  "${IPC_BIN}" >/tmp/brain_ipc_task_manager_smoke.log 2>&1 &
  IPC_PID=$!
  started_daemon=1
  for _ in {1..30}; do
    if ipc_ping; then
      break
    fi
    sleep 0.2
  done
fi

if ! ipc_ping; then
  echo "[FAIL] brain_ipc not available"
  exit 1
fi

cat >"${CFG_PATH}" <<EOF
service:
  agent_name: ${SERVICE_NAME}
  socket_path: ${SOCKET_PATH}
  health_port: 18091
  data_dir: ${DATA_DIR}
  log_file: ${LOG_PATH}
scheduler:
  deadline_reminder_interval_s: 300
  stale_task_interval_s: 3600
  stale_spec_interval_s: 3600
  deadline_warning_hours: 24
  stale_task_hours: 48
  stale_spec_hours: 72
validation:
  check_owner_online: true
EOF

BRAIN_NOTIFY_SOCKET=/tmp/brain-notify-missing.sock "${TM_BIN}" "${CFG_PATH}" >/dev/null 2>&1 &
TM_PID=$!

python3 "${ROOT_DIR}/tests/task_manager_smoke.py" \
  --socket "${SOCKET_PATH}" \
  --service-name "${SERVICE_NAME}" \
  --requester "${REQUESTER}" \
  --owner "${OWNER}" \
  --group "${GROUP_NAME}" \
  --spec-id "${SPEC_ID}"

if ! python3 - <<'PY'
import socket, sys
try:
    s=socket.create_connection(("127.0.0.1", 18091), timeout=2.0)
    s.sendall(b"GET /health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
    data = s.recv(4096)
    s.close()
    sys.exit(0 if b"200 OK" in data else 1)
except Exception:
    sys.exit(1)
PY
then
  echo "[FAIL] health endpoint check failed"
  exit 1
fi

echo "[PASS] smoke e2e ok"
