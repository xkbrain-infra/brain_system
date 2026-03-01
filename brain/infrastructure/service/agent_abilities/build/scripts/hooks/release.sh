#!/bin/bash
# Hook 版本发布脚本
# 用途: 将指定版本标记为生产版本

set -e

HOOK_ROOT="/brain/infrastructure/service/agent_abilities"
cd "$HOOK_ROOT"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# 解析参数
if [ $# -lt 1 ]; then
    echo "用法: bash scripts/release.sh <version>"
    echo "示例: bash scripts/release.sh v2"
    exit 1
fi

VERSION=$1

echo "========================================"
echo "Brain Hooks Release System"
echo "========================================"
echo ""
echo -e "${YELLOW}发布版本: $VERSION${NC}"
echo ""

# ============================================
# Step 1: 构建版本（如不存在）
# ============================================
echo "Step 1: 构建版本..."

if [ ! -d "bin/$VERSION" ]; then
    echo -e "${YELLOW}⚠ bin/$VERSION 不存在，开始构建...${NC}"
    if ! bash build/scripts/hooks/build.sh --version "$VERSION"; then
        echo -e "${RED}✗ 构建失败${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ bin/$VERSION 已存在，跳过构建${NC}"
fi

# 验证 bin 版本存在（build.sh 已负责生成）
if [ ! -d "bin/$VERSION" ]; then
    echo -e "${RED}✗ bin/$VERSION 不存在${NC}"
    exit 1
fi

echo -e "${GREEN}✓ 版本验证通过 (bin/$VERSION exists)${NC}"
echo ""

# ============================================
# Step 2: 运行测试
# ============================================
echo "Step 2: 运行测试..."

if ! bash build/scripts/hooks/test_hooks.sh; then
    echo -e "${RED}✗ 测试失败${NC}"
    exit 1
fi

echo -e "${GREEN}✓ 测试通过${NC}"
echo ""

# ============================================
# Step 3: 备份当前 production 配置
# ============================================
echo "Step 3: 备份当前配置..."

BACKUP_FILE="config/versions.yaml.backup-$(date +%Y%m%d-%H%M%S)"
cp config/versions.yaml "$BACKUP_FILE"
echo -e "${GREEN}✓ 备份到 $BACKUP_FILE${NC}"
echo ""

# ============================================
# Step 4: 更新 production 版本
# ============================================
echo "Step 4: 更新 production 版本..."

# 读取当前版本 (production: "v3.0.0")
OLD_VERSION=$(grep "^production:" config/versions.yaml | sed 's/production: *"\?\([^"]*\)"\?/\1/')

# 更新版本
sed -i "s/^production:.*/production: \"$VERSION\"/" config/versions.yaml

echo -e "${GREEN}✓ production: $OLD_VERSION -> $VERSION${NC}"
echo ""

# ============================================
# Step 5: 创建 git tag (可选)
# ============================================
echo "Step 5: 创建 git tag..."

if git rev-parse --git-dir > /dev/null 2>&1; then
    TAG_NAME="hooks-$VERSION-$(date +%Y%m%d)"

    if git tag -a "$TAG_NAME" -m "Release hooks $VERSION"; then
        echo -e "${GREEN}✓ Git tag: $TAG_NAME${NC}"
    else
        echo -e "${YELLOW}⚠ Git tag 创建失败 (可能已存在)${NC}"
    fi
else
    echo -e "${YELLOW}⚠ 不是 git 仓库，跳过 tag${NC}"
fi

echo ""

# ============================================
# Step 6: 生成 changelog
# ============================================
echo "Step 6: 生成 changelog..."

CHANGELOG_FILE="releases/RELEASE-$VERSION.md"
mkdir -p releases

cat > "$CHANGELOG_FILE" <<EOF
# Release: Hooks $VERSION

**发布日期**: $(date +%Y-%m-%d)
**发布人**: $(whoami)

## 版本信息
- 从版本: $OLD_VERSION
- 到版本: $VERSION

## 变更日志 (基于 git log)
$(git log --oneline -10 --since="2026-01-01" -- "infrastructure/service/agent_abilities/hooks/" | sed 's/^/- /')

## 详细变更
$(git diff --stat $OLD_VERSION..HEAD -- "infrastructure/service/agent_abilities/hooks/" 2>/dev/null || echo "无法获取 diff")

## 文件清单
- bin/$VERSION/: $(ls bin/$VERSION | wc -l) 个入口脚本
- 备份文件: $BACKUP_FILE

## 回滚
如需回滚，运行:
\`\`\`bash
bash scripts/rollback.sh $BACKUP_FILE
\`\`\`

## 部署
部署到所有 agents:
\`\`\`bash
bash scripts/setup_hooks.sh
\`\`\`
EOF

echo -e "${GREEN}✓ Changelog: $CHANGELOG_FILE${NC}"
echo ""

# ============================================
# 完成
# ============================================
echo "========================================"
echo -e "${GREEN}✅ 发布完成${NC}"
echo "========================================"
echo ""
echo "版本: $OLD_VERSION -> $VERSION"
echo "Changelog: $CHANGELOG_FILE"
echo "备份: $BACKUP_FILE"
echo ""
echo "下一步:"
echo "  bash scripts/setup_hooks.sh  # 部署到所有 agents"
echo ""
