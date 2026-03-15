#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/brain/infrastructure/service/task-manager"
ARCHIVE_ROOT="/brain/runtime/memory/testing/task-manager/$(date +%F)"
mkdir -p "${ARCHIVE_ROOT}"

LOG_FILE="${ARCHIVE_ROOT}/test.log"
SUMMARY_FILE="${ARCHIVE_ROOT}/summary.md"
REPORT_FILE="${ARCHIVE_ROOT}/report.json"

{
  echo "[INFO] build task-manager"
  cd "${ROOT_DIR}"
  make clean
  make

  echo "[INFO] run eventloop baseline"
  bash tests/eventloop_baseline.sh

  echo "[INFO] run smoke e2e"
  bash tests/smoke_e2e.sh
} | tee "${LOG_FILE}"

cat > "${SUMMARY_FILE}" <<EOF
# Task Manager Containerized Test Summary

- Date: $(date -Iseconds)
- Suite: BS-017 task-manager
- Result: PASS
- Passed: 2
- Failed: 0
- Skipped: 0
- Details:
  - tests/eventloop_baseline.sh
  - tests/smoke_e2e.sh
EOF

cat > "${REPORT_FILE}" <<EOF
{
  "suite": "task-manager",
  "status": "pass",
  "timestamp": "$(date -Iseconds)",
  "passed": 2,
  "failed": 0,
  "skipped": 0,
  "cases": [
    {"name": "eventloop_baseline", "status": "pass"},
    {"name": "smoke_e2e", "status": "pass"}
  ],
  "artifacts": {
    "log": "${LOG_FILE}",
    "summary": "${SUMMARY_FILE}"
  }
}
EOF

echo "[PASS] all tests passed"
