#!/bin/bash
# deploy/services/agent_abilities/deploy.sh
# 把 bin/hooks/current/ 下的 hooks 部署到所有 Claude agent 的 .claude/hooks/
#
# 用法:
#   ./deploy.sh [hooks]         部署 hooks（默认）
#   ./deploy.sh hooks --dry-run 只显示，不实际部署

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_LIB="$(cd "$SCRIPT_DIR/../../lib" && pwd)"
AGENT_ABILITIES="/brain/infrastructure/service/agent_abilities"
HOOKS_CURRENT="$AGENT_ABILITIES/bin/hooks/current"

# shellcheck source=../../lib/common.sh
source "$DEPLOY_LIB/common.sh"

SUBCMD="${1:-hooks}"
DRY_RUN=false
[[ "${2:-}" == "--dry-run" ]] && DRY_RUN=true

# ─── hooks 文件列表 ──────────────────────────────────────────────────
HOOK_FILES=(
    "pre_tool_use"
    "post_tool_use"
    "user_prompt_submit"
    "session_start"
    "session_end"
)

# ─── 部署 hooks ──────────────────────────────────────────────────────
deploy_hooks() {
    log "Source: $HOOKS_CURRENT"

    # 验证 source 目录存在
    if [ ! -d "$HOOKS_CURRENT" ]; then
        fail "hooks current not found: $HOOKS_CURRENT"
    fi

    # 验证 hook 文件存在
    for hook in "${HOOK_FILES[@]}"; do
        if [ ! -f "$HOOKS_CURRENT/$hook" ]; then
            warn "Hook file missing in current: $hook (will skip agents)"
        fi
    done

    echo -e "${BOLD}══ Deploying hooks to all Claude agents ══${RESET}"
    echo ""

    # 遍历所有有 .claude 目录的 agent
    while IFS= read -r claude_dir; do
        local agent_dir
        agent_dir="$(dirname "$claude_dir")"
        local agent_name
        agent_name="$(basename "$agent_dir")"

        # 创建 hooks 子目录
        local hooks_dir="$claude_dir/hooks"

        if $DRY_RUN; then
            log "[DRY-RUN] Would deploy to: $hooks_dir"
            count_skip
            continue
        fi

        # 部署每个 hook 文件
        mkdir -p "$hooks_dir"
        local agent_ok=true
        for hook in "${HOOK_FILES[@]}"; do
            local src="$HOOKS_CURRENT/$hook"
            if [ ! -f "$src" ]; then
                continue  # 跳过缺失的 hook 文件
            fi
            if deploy_file "$src" "$hooks_dir" 755; then
                true
            else
                warn "Failed to deploy $hook → $agent_name"
                agent_ok=false
            fi
        done

        if $agent_ok; then
            ok "$agent_name → $hooks_dir"
            count_ok
        else
            warn "$agent_name → partial failure"
            count_fail
        fi
    done < <(list_claude_agents)

    print_summary "hooks deploy"
}

# ─── Main ────────────────────────────────────────────────────────────
case "$SUBCMD" in
    hooks)
        deploy_hooks
        ;;
    *)
        echo "Usage: $0 [hooks] [--dry-run]"
        echo ""
        echo "  hooks       Deploy hooks from bin/hooks/current/ to all Claude agents"
        echo "  --dry-run   Show what would be deployed without actually deploying"
        exit 1
        ;;
esac
