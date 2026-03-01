#!/bin/bash
# Hook 版本回滚脚本 (BS-012-T4)
# 用途: 快速回退到上一个稳定版本
# 增强: 支持 --yes 无交互模式

set -e

HOOK_ROOT="/brain/infrastructure/service/agent_abilities"
cd "$HOOK_ROOT"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# ========================================
# 解析参数
# ========================================
NON_INTERACTIVE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --yes|-y)
            NON_INTERACTIVE=true
            shift
            ;;
        --help|-h)
            echo "Usage: bash scripts/rollback.sh [OPTIONS] [backup_file]"
            echo ""
            echo "Options:"
            echo "  --yes, -y    无交互模式，自动确认回滚"
            echo "  --help, -h   显示帮助"
            echo ""
            echo "Examples:"
            echo "  bash scripts/rollback.sh                           # 使用最新备份"
            echo "  bash scripts/rollback.sh config/versions.yaml.backup-20260213"
            echo "  bash scripts/rollback.sh --yes                     # 自动确认"
            exit 0
            ;;
        *)
            BACKUP_FILE=$1
            shift
            ;;
    esac
done

echo "========================================"
echo "Brain Hooks Rollback System (BS-012-T4)"
echo "========================================"
echo ""

# ========================================
# 查找备份文件
# ========================================
if [ -z "$BACKUP_FILE" ]; then
    BACKUP_FILE=$(ls -t config/versions.yaml.backup-* 2>/dev/null | head -1)

    if [ -z "$BACKUP_FILE" ]; then
        echo -e "${RED}✗ 没有找到备份文件${NC}"
        echo "用法: bash scripts/rollback.sh <backup_file>"
        echo "示例: bash scripts/rollback.sh config/versions.yaml.backup-20260213-183000"
        exit 1
    fi

    echo -e "${YELLOW}使用最新备份: $BACKUP_FILE${NC}"
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo -e "${RED}✗ 备份文件不存在: $BACKUP_FILE${NC}"
    exit 1
fi

echo ""

# ========================================
# Step 1: 读取版本信息
# ========================================
echo "Step 1: 读取版本信息..."

CURRENT_VERSION=$(grep "^production:" config/versions.yaml | sed 's/production: *"\?\([^"]*\)"\?/\1/')
TARGET_VERSION=$(grep "^production:" "$BACKUP_FILE" | sed 's/production: *"\?\([^"]*\)"\?/\1/')

echo "  当前版本: $CURRENT_VERSION"
echo "  目标版本: $TARGET_VERSION"
echo ""

# ========================================
# Step 2: 确认操作
# ========================================
if [ "$NON_INTERACTIVE" = true ]; then
    echo -e "${YELLOW}⚠️  无交互模式: 即将回滚到 $TARGET_VERSION${NC}"
    confirm="y"
else
    echo -e "${YELLOW}⚠️  即将回滚到 $TARGET_VERSION${NC}"
    echo -n "继续? (y/n): "
    read -r confirm
fi

if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "取消回滚"
    exit 0
fi

echo ""

# ========================================
# Step 3: 验证目标版本存在
# ========================================
echo "Step 3: 验证目标版本..."

if [ ! -d "bin/$TARGET_VERSION" ]; then
    echo -e "${RED}✗ bin/$TARGET_VERSION 不存在${NC}"
    exit 1
fi

echo -e "${GREEN}✓ 目标版本存在${NC}"
echo ""

# ========================================
# Step 4: 备份当前配置
# ========================================
echo "Step 4: 备份当前配置..."

ROLLBACK_BACKUP="config/versions.yaml.rollback-$(date +%Y%m%d-%H%M%S)"
cp config/versions.yaml "$ROLLBACK_BACKUP"

echo -e "${GREEN}✓ 备份到 $ROLLBACK_BACKUP${NC}"
echo ""

# ========================================
# Step 5: 恢复配置
# ========================================
echo "Step 5: 恢复配置..."

cp "$BACKUP_FILE" config/versions.yaml

echo -e "${GREEN}✓ 恢复 versions.yaml${NC}"
echo ""

# ========================================
# Step 6: 更新 bin/current symlink
# ========================================
echo "Step 6: 更新 bin/current..."

if [ -L "bin/current" ]; then
    rm bin/current
fi

ln -s "$TARGET_VERSION" bin/current

echo -e "${GREEN}✓ bin/current -> $TARGET_VERSION${NC}"
echo ""

# ========================================
# Step 7: 验证 hooks
# ========================================
echo "Step 7: 验证 hooks..."

if bash scripts/test_hooks.sh 2>&1 | tail -5; then
    echo -e "${GREEN}✓ Hooks 验证通过${NC}"
else
    echo -e "${RED}✗ Hooks 验证失败${NC}"
    echo ""
    echo "尝试恢复..."
    cp "$ROLLBACK_BACKUP" config/versions.yaml
    rm bin/current
    ln -s "$CURRENT_VERSION" bin/current
    echo -e "${RED}已恢复到 $CURRENT_VERSION${NC}"
    exit 1
fi

echo ""

# ========================================
# Step 8: 生成回滚报告
# ========================================
ROLLBACK_REPORT="releases/ROLLBACK-$(date +%Y%m%d-%H%M%S).md"
mkdir -p releases

cat > "$ROLLBACK_REPORT" <<EOF
# Rollback Report

**回滚时间**: $(date +%Y-%m-%d\ %H:%M:%S)
**操作人**: $(whoami)
**模式**: $([ "$NON_INTERACTIVE" = true ] && echo "非交互" || echo "交互")

## 版本变更
- 从版本: $CURRENT_VERSION
- 到版本: $TARGET_VERSION

## 备份文件
- 使用备份: $BACKUP_FILE
- 当前配置备份: $ROLLBACK_BACKUP

## 如需再次回滚
\`\`\`bash
bash scripts/rollback.sh $ROLLBACK_BACKUP
\`\`\`
EOF

echo -e "${GREEN}✓ 回滚报告: $ROLLBACK_REPORT${NC}"
echo ""

# ========================================
# 完成
# ========================================
echo "========================================"
echo -e "${GREEN}✅ 回滚完成${NC}"
echo "========================================"
echo ""
echo "版本: $CURRENT_VERSION -> $TARGET_VERSION"
echo "报告: $ROLLBACK_REPORT"
echo ""
echo "下一步:"
echo "  bash scripts/setup_hooks.sh  # 部署到所有 agents"
echo ""
