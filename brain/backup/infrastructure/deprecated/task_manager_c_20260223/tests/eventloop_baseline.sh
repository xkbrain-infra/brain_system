#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BIN_PATH="${ROOT_DIR}/build/service-task_manager"
IPC_BIN="${ROOT_DIR}/tests/bin/brain_ipc"
if [[ ! -x "${IPC_BIN}" ]]; then
  IPC_BIN="/brain/infrastructure/service/brain_ipc/releases/v1.0.0/bin/brain_ipc"
fi
if [[ ! -x "${BIN_PATH}" ]]; then
  BIN_PATH="${ROOT_DIR}/bin/current/service-task_manager"
fi

if [[ ! -x "${BIN_PATH}" ]]; then
  echo "[FAIL] service-task_manager binary not found"
  exit 1
fi

TMP_DIR="$(mktemp -d /tmp/tm-eventloop-test.XXXXXX)"
CFG_PATH="${TMP_DIR}/task_manager.yaml"
LOG_PATH="${TMP_DIR}/task_manager.log"
DATA_DIR="${TMP_DIR}/data"
mkdir -p "${DATA_DIR}"

started_daemon=0

cleanup() {
  if [[ -n "${TPID:-}" ]] && kill -0 "${TPID}" 2>/dev/null; then
    kill -TERM "${TPID}" 2>/dev/null || true
    wait "${TPID}" 2>/dev/null || true
  fi
  if [[ "${started_daemon}" -eq 1 ]]; then
    "${IPC_BIN}" stop >/dev/null 2>&1 || true
    wait "${DPID:-0}" 2>/dev/null || true
  fi
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

ipc_ping() {
  python3 - <<'PY'
import json, socket, sys
try:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(0.8)
    s.connect("/tmp/brain_ipc.sock")
    s.sendall(b'{"action":"ping","data":{}}\n')
    buf = b""
    while True:
        c = s.recv(4096)
        if not c:
            break
        buf += c
        if b"\n" in buf:
            break
    s.close()
    obj = json.loads(buf.decode("utf-8"))
    sys.exit(0 if obj.get("status") in ("ok", "pong") else 1)
except Exception:
    sys.exit(1)
PY
}

if ! ipc_ping; then
  if [[ ! -x "${IPC_BIN}" ]]; then
    echo "[FAIL] brain_ipc binary not found"
    exit 1
  fi
  "${IPC_BIN}" >/tmp/brain_ipc_task_manager_eventloop.log 2>&1 &
  DPID=$!
  started_daemon=1
  for _ in {1..30}; do
    if ipc_ping; then
      break
    fi
    sleep 0.2
  done
fi

if ! ipc_ping; then
  echo "[FAIL] brain_ipc unavailable"
  exit 1
fi

cat >"${CFG_PATH}" <<EOF
service:
  agent_name: service-task_manager-eventloop-test
  socket_path: /tmp/brain_ipc.sock
  data_dir: ${DATA_DIR}
  log_file: ${LOG_PATH}
scheduler:
  deadline_reminder_interval_s: 300
  stale_task_interval_s: 3600
  stale_spec_interval_s: 3600
  deadline_warning_hours: 24
  stale_task_hours: 48
  stale_spec_hours: 72
EOF

# Force notify unavailable and ensure process remains low-cpu.
BRAIN_NOTIFY_SOCKET=/tmp/brain-notify-missing.sock "${BIN_PATH}" "${CFG_PATH}" >/dev/null 2>&1 &
TPID=$!
sleep 1

if ! kill -0 "${TPID}" 2>/dev/null; then
  echo "[FAIL] service failed to stay alive"
  exit 1
fi

start_ticks="$(awk '{print $14+$15}' "/proc/${TPID}/stat")"
sleep 5
end_ticks="$(awk '{print $14+$15}' "/proc/${TPID}/stat")"
delta_ticks=$((end_ticks - start_ticks))

# 5s window; delta over 25 ticks indicates visible busy loop.
if (( delta_ticks > 25 )); then
  echo "[FAIL] high cpu in disconnected-notify mode, delta_ticks=${delta_ticks}"
  exit 1
fi

if ! grep -Eq "notify reconnect failed|notify socket unavailable" "${LOG_PATH}"; then
  echo "[FAIL] notify disconnect/backoff log not found"
  exit 1
fi

echo "[PASS] event loop baseline ok (delta_ticks=${delta_ticks})"
