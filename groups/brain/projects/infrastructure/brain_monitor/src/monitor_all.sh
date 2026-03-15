#!/bin/bash
# Brain System 一键监控脚本

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RELEASES_ROOT="$(dirname "$SCRIPT_DIR")"
BIN_DIR="$RELEASES_ROOT/bin"

echo "=== Brain System Monitor ==="
echo ""
echo "1. Agent Status"
"$BIN_DIR/agents_status"
echo ""
echo "2. IPC Statistics (Last 1 hour)"
"$BIN_DIR/ipc_stats" --hours 1
echo ""
echo "3. Task Monitor (Last 1 hour)"
"$BIN_DIR/task_monitor" --hours 1
