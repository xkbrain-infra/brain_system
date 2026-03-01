#!/bin/bash
# MCP Server 构建脚本 (brain_ipc_c)
# 用法: build.sh [all|clean]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SRC_DIR="$SERVICE_DIR/src/base/mcp/brain_ipc_c"
BIN_DIR="$SERVICE_DIR/bin/mcp"

GREEN='\033[32m'; CYAN='\033[36m'; RED='\033[31m'; RESET='\033[0m'
log()  { echo -e "${CYAN}[mcp-build]${RESET} $1"; }
ok()   { echo -e "${GREEN}[mcp-build]${RESET} $1"; }
fail() { echo -e "${RED}[mcp-build]${RESET} $1"; exit 1; }

CMD="${1:-all}"

case "$CMD" in
    all)
        log "Building brain_ipc_c MCP server..."
        [ -f "$SRC_DIR/Makefile" ] || fail "Makefile not found: $SRC_DIR/Makefile"
        mkdir -p "$BIN_DIR"
        make -C "$SRC_DIR" all
        # 复制产物到 bin/mcp/
        if [ -f "$SRC_DIR/bin/brain_ipc_c_mcp_server" ]; then
            cp "$SRC_DIR/bin/brain_ipc_c_mcp_server" "$BIN_DIR/"
            ok "Copied to $BIN_DIR/brain_ipc_c_mcp_server"
        else
            fail "Build succeeded but binary not found at $SRC_DIR/bin/"
        fi
        ok "MCP server build complete"
        ;;
    clean)
        log "Cleaning..."
        make -C "$SRC_DIR" clean 2>/dev/null || true
        ok "Clean complete"
        ;;
    *)
        echo "Usage: $0 [all|clean]"
        exit 1
        ;;
esac
