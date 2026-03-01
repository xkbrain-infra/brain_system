#!/bin/bash
# deploy/services/brain_gateway/deploy.sh
# brain_gateway 部署脚本（通过 supervisord 重启）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/../../lib/common.sh"

SUBCMD="${1:-restart}"

case "$SUBCMD" in
    restart)
        log "Restarting brain_gateway via supervisord..."
        if command -v supervisorctl >/dev/null 2>&1; then
            supervisorctl restart brain_gateway && ok "brain_gateway restarted" || fail "Failed to restart brain_gateway"
        else
            warn "supervisorctl not found, skipping brain_gateway restart"
        fi
        ;;
    *)
        echo "Usage: $0 [restart]"
        exit 1
        ;;
esac
