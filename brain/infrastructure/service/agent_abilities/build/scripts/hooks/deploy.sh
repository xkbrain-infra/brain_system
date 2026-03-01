#!/bin/bash
# Hooks 部署脚本
# 功能：将编译产物部署到各个 agent

set -e

HOOK_ROOT="/brain/infrastructure/service/agent_abilities"
BUILD_DIR="$HOOK_ROOT/build"
RELEASES_DIR="$HOOK_ROOT/releases"

# 颜色输出
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 解析参数
VERSION="${1:-latest}"
ROLE="${2:-all}"

if [ "$VERSION" = "latest" ]; then
    # 使用 build/ 目录
    DEPLOY_SOURCE="$BUILD_DIR"
else
    # 使用 releases/ 目录
    DEPLOY_SOURCE="$RELEASES_DIR/$VERSION"

    if [ ! -d "$DEPLOY_SOURCE" ]; then
        echo -e "${RED}✗${NC} 版本不存在: $VERSION"
        exit 1
    fi
fi

echo "========================================"
echo "Hooks 部署系统"
echo "========================================"
echo ""
echo "部署源: $DEPLOY_SOURCE"
echo "部署角色: $ROLE"
echo ""

# 定义角色到 agent 的映射
declare -A ROLE_AGENTS

ROLE_AGENTS[pmo]="agent_system_pmo agent_xkquant_pmo"
ROLE_AGENTS[architect]="agent_system_architect agent_xkquant_architect"
ROLE_AGENTS[dev]="agent_system_dev1 agent_system_dev2"
ROLE_AGENTS[qa]="agent_system_qa agent_system_qa1 agent_system_qa2 agent_xkquant_qa"
ROLE_AGENTS[devops]="agent_system_devops agent_xkquant_devops"
ROLE_AGENTS[frontdesk]="agent_system_frontdesk"

deploy_to_agent() {
    local agent_name=$1
    local role=$2
    local agent_dir="/brain/groups/org/brain_system/agents/$agent_name"

    # 查找 agent 目录（支持多个 org）
    if [ ! -d "$agent_dir" ]; then
        agent_dir=$(find /brain/groups/org -name "$agent_name" -type d | head -1)
    fi

    if [ ! -d "$agent_dir" ]; then
        echo -e "${YELLOW}⚠${NC}  Agent 不存在: $agent_name"
        return 1
    fi

    echo "  部署到: $agent_name"

    # 1. 部署 bin 文件（硬链接）
    mkdir -p "$agent_dir/.claude/hooks"

    for hook_file in "$DEPLOY_SOURCE/bin"/*; do
        if [ -f "$hook_file" ]; then
            hook_name=$(basename "$hook_file")
            ln -f "$hook_file" "$agent_dir/.claude/hooks/$hook_name"
        fi
    done

    # 2. 部署 settings.json
    if [ "$role" = "global" ]; then
        settings_file="$DEPLOY_SOURCE/configs/settings.global.json"
    else
        settings_file="$DEPLOY_SOURCE/configs/settings.roles/settings.$role.json"
    fi

    if [ -f "$settings_file" ]; then
        # 合并到现有 settings.local.json
        if [ -f "$agent_dir/.claude/settings.local.json" ]; then
            # 备份
            cp "$agent_dir/.claude/settings.local.json" \
               "$agent_dir/.claude/settings.local.json.bak"

            # 合并（使用 Python）
            python3 -c "
import json
with open('$settings_file') as f:
    new_settings = json.load(f)
with open('$agent_dir/.claude/settings.local.json') as f:
    old_settings = json.load(f)

# 合并 hooks
old_settings['hooks'] = new_settings.get('hooks', {})

with open('$agent_dir/.claude/settings.local.json', 'w') as f:
    json.dump(old_settings, f, indent=2, ensure_ascii=False)
"
        else
            # 直接复制
            cp "$settings_file" "$agent_dir/.claude/settings.local.json"
        fi
    fi

    # 3. 部署 lep.yaml (角色特定规则)
    if [ "$role" = "global" ]; then
        # 全局规则使用 base/spec/core/lep.yaml
        lep_file="/brain/base/spec/core/lep.yaml"
        if [ -f "$lep_file" ]; then
            cp "$lep_file" "$agent_dir/.claude/lep.yaml"
        fi
    else
        # 角色特定规则
        lep_file="$DEPLOY_SOURCE/configs/merged_rules/lep.$role.yaml"
        if [ -f "$lep_file" ]; then
            cp "$lep_file" "$agent_dir/.claude/lep.yaml"
        else
            # 回退到全局规则
            cp "/brain/base/spec/core/lep.yaml" "$agent_dir/.claude/lep.yaml"
        fi
    fi

    echo -e "    ${GREEN}✓${NC} 部署成功"
}

# 执行部署
if [ "$ROLE" = "all" ]; then
    # 部署到所有角色
    for role in pmo architect dev qa devops frontdesk; do
        echo ""
        echo "部署角色: $role"
        echo "---"

        agents="${ROLE_AGENTS[$role]}"
        for agent in $agents; do
            deploy_to_agent "$agent" "$role"
        done
    done
else
    # 部署到指定角色
    echo "部署角色: $ROLE"
    echo "---"

    agents="${ROLE_AGENTS[$ROLE]}"

    if [ -z "$agents" ]; then
        echo -e "${RED}✗${NC} 未知角色: $ROLE"
        echo ""
        echo "可用角色: pmo, architect, dev, qa, devops, frontdesk, all"
        exit 1
    fi

    for agent in $agents; do
        deploy_to_agent "$agent" "$ROLE"
    done
fi

echo ""
echo "========================================"
echo -e "${GREEN}✅ 部署完成！${NC}"
echo "========================================"
echo ""
echo "验证部署："
echo "  cd /brain/groups/org/brain_system/agents/agent_system_pmo"
echo "  cat .claude/settings.local.json | jq .hooks"
echo ""
