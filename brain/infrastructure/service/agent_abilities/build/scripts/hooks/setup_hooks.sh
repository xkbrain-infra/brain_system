#!/bin/bash
# Setup Hooks - 使用硬链接部署到所有 Agents

set -e

HOOK_BIN="/brain/infrastructure/hooks/bin/current"
AGENTS_ROOT="/brain/groups"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================"
echo "Brain Hook Setup - 统一 Hook 治理 v2"
echo "========================================"
echo ""
echo "Hook 源: $HOOK_BIN"
echo "Agent 根: $AGENTS_ROOT"
echo ""

# Hook 文件映射
declare -A HOOKS=(
    ["session_start"]="session_start.py"
    ["pre_tool_use"]="pre_tool_use.py"
    ["post_tool_use"]="post_tool_use.py"
    ["user_prompt_submit"]="user_prompt_submit.py"
)

total=0
success=0

# 查找所有 agent 目录（只处理 Claude agents，Codex agents 使用 .codex）
for agent_dir in $(find "$AGENTS_ROOT" -type d -path "*/agents/agent_*" 2>/dev/null | sort); do
    agent_name=$(basename "$agent_dir")
    hook_dir="$agent_dir/.claude/hooks"

    # 跳过 Codex agents（它们使用 .codex 目录）
    if [ ! -d "$agent_dir/.claude" ]; then
        continue
    fi

    mkdir -p "$hook_dir" 2>/dev/null || continue

    echo -e "${YELLOW}设置: $agent_name${NC}"

    created=0
    for hook_name in "${!HOOKS[@]}"; do
        src="$HOOK_BIN/$hook_name"
        dst="$hook_dir/${HOOKS[$hook_name]}"

        if [ ! -f "$src" ]; then
            continue
        fi

        # 使用硬链接（不是 symlink）
        ln -f "$src" "$dst" 2>/dev/null && ((created++)) || true
    done

    if [ $created -gt 0 ]; then
        echo -e "  ${GREEN}✅ $created hooks${NC}"
        ((success++))
    fi
    ((total++))
done

echo ""
echo "========================================"
echo -e "${GREEN}✅ 完成！$success/$total agents${NC}"
echo "========================================"
echo ""
echo "验证："
echo "  ls -la /brain/groups/org/brain_system/agents/agent_system_pmo/.claude/hooks/"
echo ""
echo "测试："
echo "  python3 $HOOK_BIN/pre_tool_use <<< '{\"hookEventName\": \"PreToolUse\", \"toolName\": \"Write\", \"toolInput\": {\"file_path\": \"/tmp/test.yaml\"}}'"
