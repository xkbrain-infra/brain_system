#!/bin/bash
# deploy/deploy.sh — 统一部署入口
#
# 用法:
#   ./deploy.sh <service> [target] [--dry-run]   部署指定服务/目标
#   ./deploy.sh all                               部署全部服务
#   ./deploy.sh list                              列出注册的服务

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_LIB="$SCRIPT_DIR/lib"

RED='\033[31m'
GREEN='\033[32m'
YELLOW='\033[33m'
CYAN='\033[36m'
BOLD='\033[1m'
RESET='\033[0m'

log()  { echo -e "${CYAN}[deploy]${RESET} $1"; }
ok()   { echo -e "${GREEN}[deploy] ✓${RESET} $1"; }
warn() { echo -e "${YELLOW}[deploy] ⚠${RESET} $1"; }
fail() { echo -e "${RED}[deploy] ✗${RESET} $1"; exit 1; }

# ─── 已注册的服务 ────────────────────────────────────────────────────
declare -A SERVICE_SCRIPTS=(
    [brain_gateway]="services/brain_gateway/deploy.sh"
    [task_manager]="services/task_manager/deploy.sh"
)

# ─── list: 列出服务 ──────────────────────────────────────────────────
cmd_list() {
    echo -e "${BOLD}══ Registered Deploy Services ══${RESET}"
    echo ""
    for svc in "${!SERVICE_SCRIPTS[@]}"; do
        local script="$SCRIPT_DIR/${SERVICE_SCRIPTS[$svc]}"
        if [ -f "$script" ]; then
            echo -e "  ${GREEN}●${RESET} $svc"
            echo -e "    script: ${SERVICE_SCRIPTS[$svc]}"
        else
            echo -e "  ${YELLOW}○${RESET} $svc"
            echo -e "    script: ${SERVICE_SCRIPTS[$svc]} ${YELLOW}(not implemented)${RESET}"
        fi
        echo ""
    done
}

# ─── run_service: 执行服务 deploy.sh ────────────────────────────────
run_service() {
    local svc="$1"
    local target="${2:-}"
    local dry_run="${3:-}"

    if [ -z "${SERVICE_SCRIPTS[$svc]:-}" ]; then
        fail "Unknown service: $svc (use 'list' to see registered services)"
    fi

    local script="$SCRIPT_DIR/${SERVICE_SCRIPTS[$svc]}"
    if [ ! -f "$script" ]; then
        warn "Service script not implemented: $script"
        return 0
    fi

    chmod +x "$script"
    local args=()
    [ -n "$target" ] && args+=("$target")
    [ -n "$dry_run" ] && args+=("$dry_run")

    bash "$script" "${args[@]}"
}

# ─── Main ────────────────────────────────────────────────────────────
CMD="${1:-help}"

case "$CMD" in
    list)
        cmd_list
        ;;
    all)
        echo -e "${BOLD}══ Deploying all services ══${RESET}"
        DRY_RUN_ARG="${2:-}"
        for svc in brain_gateway task_manager; do
            log "Service: $svc"
            run_service "$svc" "" "$DRY_RUN_ARG" || warn "$svc deploy failed"
        done
        ok "All services processed"
        ;;
    brain_gateway|task_manager)
        SVC="$CMD"
        TARGET="${2:-}"
        DRY_RUN_ARG="${3:-}"
        log "Deploying: $SVC ${TARGET:+(target: $TARGET)}"
        run_service "$SVC" "$TARGET" "$DRY_RUN_ARG"
        ;;
    help|--help|-h)
        echo "Usage: $0 <command> [args]"
        echo ""
        echo "Commands:"
        echo "  list                             List registered deploy services"
        echo "  all [--dry-run]                  Deploy all services"
        echo "  <service> [target] [--dry-run]   Deploy specific service/target"
        echo ""
        echo "Services:"
        for svc in "${!SERVICE_SCRIPTS[@]}"; do
            echo "  $svc"
        done
        echo ""
        echo "Examples:"
        echo "  $0 brain_gateway restart"
        echo "  $0 list"
        ;;
    *)
        fail "Unknown command: $CMD (use 'help' or 'list')"
        ;;
esac
