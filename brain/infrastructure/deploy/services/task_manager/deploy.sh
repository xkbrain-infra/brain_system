#!/bin/bash
# deploy/services/task_manager/deploy.sh
# task_manager 部署脚本（通过 supervisord 重启）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/../../lib/common.sh"

SUBCMD="${1:-restart}"

case "$SUBCMD" in
    restart)
        log "Restarting task_manager via supervisord..."
        if command -v supervisorctl >/dev/null 2>&1; then
            supervisorctl restart service-task_manager && ok "task_manager restarted" || fail "Failed to restart task_manager"
        else
            warn "supervisorctl not found, skipping task_manager restart"
        fi
        ;;
    *)
        echo "Usage: $0 [restart]"
        exit 1
        ;;
esac
