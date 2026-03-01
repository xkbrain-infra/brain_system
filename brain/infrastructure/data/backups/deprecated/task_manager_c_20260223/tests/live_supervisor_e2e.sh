#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SOCKET_PATH="/tmp/brain_ipc.sock"
SERVICE_NAME="service-task_manager"
REQUESTER="agent_live_e2e_req_$$"
OWNER="agent_live_e2e_owner_$$"
GROUP_NAME="system"
SPEC_ID="LIVE-SMOKE-$(date +%s)-$$"
SPEC_DIR="/brain/groups/org/${GROUP_NAME}/spec/${SPEC_ID}"

cleanup() {
  rm -rf "${SPEC_DIR}" 2>/dev/null || true
}
trap cleanup EXIT

ipc_ping() {
  python3 - <<'PY'
import json, socket, sys
sock="/tmp/brain_ipc.sock"
try:
    s=socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(1.0)
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
  echo "[FAIL] brain_ipc unavailable: ${SOCKET_PATH}"
  exit 1
fi

status_line="$(supervisorctl status "${SERVICE_NAME}" || true)"
if [[ "${status_line}" != *"RUNNING"* ]]; then
  supervisorctl start "${SERVICE_NAME}" >/dev/null
  for _ in {1..30}; do
    status_line="$(supervisorctl status "${SERVICE_NAME}" || true)"
    if [[ "${status_line}" == *"RUNNING"* ]]; then
      break
    fi
    sleep 1
  done
fi

status_line="$(supervisorctl status "${SERVICE_NAME}" || true)"
if [[ "${status_line}" != *"RUNNING"* ]]; then
  echo "[FAIL] ${SERVICE_NAME} not running under supervisor"
  echo "${status_line}"
  exit 1
fi

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
    s = socket.create_connection(("127.0.0.1", 8091), timeout=2.0)
    s.sendall(b"GET /health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
    chunks = []
    while True:
        c = s.recv(4096)
        if not c:
            break
        chunks.append(c)
    s.close()
    data = b"".join(chunks)
    sys.exit(0 if b"200 OK" in data and b"\"status\":\"healthy\"" in data else 1)
except Exception:
    sys.exit(1)
PY
then
  echo "[FAIL] health endpoint check failed on 127.0.0.1:8091"
  exit 1
fi

echo "[PASS] live supervisor e2e ok"
