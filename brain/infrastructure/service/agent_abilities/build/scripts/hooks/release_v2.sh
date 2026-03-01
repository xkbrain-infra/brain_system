#!/bin/bash
# Hooks V2 Release Script
# 用途: 将 build/ 产物打包成版本发布

set -e

HOOK_ROOT="/brain/infrastructure/service/agent_abilities"
cd "$HOOK_ROOT"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# 解析参数
if [ $# -lt 1 ]; then
    echo "用法: bash scripts/release_v2.sh <version>"
    echo "示例: bash scripts/release_v2.sh v2.1.0"
    exit 1
fi

VERSION=$1

echo "========================================"
echo "Hooks V2 Release System"
echo "========================================"
echo ""
echo -e "${YELLOW}发布版本: $VERSION${NC}"
echo ""

# ============================================
# Step 1: 验证 build 产物存在
# ============================================
echo "Step 1: 验证构建产物..."

if [ ! -d "build/bin" ]; then
    echo -e "${RED}✗ build/bin 不存在${NC}"
    echo "请先运行: bash scripts/build_v2.sh"
    exit 1
fi

if [ ! -d "build/configs" ]; then
    echo -e "${RED}✗ build/configs 不存在${NC}"
    echo "请先运行: bash scripts/build_v2.sh"
    exit 1
fi

echo -e "${GREEN}✓ 构建产物存在${NC}"
echo ""

# ============================================
# Step 2: 创建发布目录
# ============================================
echo "Step 2: 创建发布目录..."

RELEASE_DIR="releases/$VERSION"

if [ -d "$RELEASE_DIR" ]; then
    echo -e "${YELLOW}⚠ $RELEASE_DIR 已存在${NC}"
    read -p "是否覆盖? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "取消发布"
        exit 1
    fi
    rm -rf "$RELEASE_DIR"
fi

mkdir -p "$RELEASE_DIR"
echo -e "${GREEN}✓ 创建 $RELEASE_DIR${NC}"
echo ""

# ============================================
# Step 3: 复制产物
# ============================================
echo "Step 3: 复制产物..."

# 复制 bin
cp -r build/bin "$RELEASE_DIR/"
echo -e "${GREEN}✓ 复制 bin/$(ls build/bin | wc -l) 个文件${NC}"

# 复制 configs
cp -r build/configs "$RELEASE_DIR/"
echo -e "${GREEN}✓ 复制 configs/${NC}"

echo ""

# ============================================
# Step 4: 生成 CHANGELOG
# ============================================
echo "Step 4: 生成 CHANGELOG..."

CHANGELOG_FILE="$RELEASE_DIR/CHANGELOG.md"

# 统计信息
BIN_COUNT=$(ls build/bin | wc -l)
GLOBAL_CONFIG_COUNT=$(find build/configs -name "settings.global.json" | wc -l)
ROLE_CONFIG_COUNT=$(find build/configs/settings.roles -name "*.json" | wc -l)
MERGED_RULES_COUNT=$(find build/configs/merged_rules -name "*.yaml" | wc -l)

cat > "$CHANGELOG_FILE" <<EOF
# Hooks V2 Release: $VERSION

**发布日期**: $(date +%Y-%m-%d %H:%M:%S)
**发布人**: $(whoami)

## 产物清单

### 可执行文件 (bin/)
- 文件数: $BIN_COUNT
- 文件列表:
$(ls -1 build/bin/ | sed 's/^/  - /')

### 配置文件 (configs/)

#### 全局配置
- settings.global.json (1 个)

#### 角色配置 (settings.roles/)
- 配置数: $ROLE_CONFIG_COUNT
- 文件列表:
$(ls -1 build/configs/settings.roles/ | sed 's/^/  - /')

#### 合并规则 (merged_rules/)
- 规则文件数: $MERGED_RULES_COUNT
- 文件列表:
$(ls -1 build/configs/merged_rules/ | sed 's/^/  - /')

## 版本信息

### Matcher 配置
所有角色使用相同的 matcher:
\`\`\`
$(jq -r '.hooks.PreToolUse[0].matcher' build/configs/settings.global.json)
\`\`\`

### 规则统计
$(for role in pmo architect dev qa; do
    count=$(grep -c "^  G-" build/configs/merged_rules/lep.$role.yaml || echo 0)
    echo "- $role: $count 个 gates"
done)

## 部署

### 部署到特定角色
\`\`\`bash
bash scripts/deploy.sh $VERSION <role>
# role: pmo, architect, dev, qa
\`\`\`

### 部署到所有角色
\`\`\`bash
bash scripts/deploy.sh $VERSION all
\`\`\`

## 回滚
如需回滚到之前版本:
\`\`\`bash
bash scripts/deploy.sh <old_version> all
\`\`\`

## 测试
测试 hook 是否正常工作:
\`\`\`bash
echo '{"hookEventName":"PreToolUse","toolName":"Write","toolInput":{"file_path":"/test.py"}}' | \\
  $RELEASE_DIR/bin/pre_tool_use
\`\`\`
EOF

echo -e "${GREEN}✓ CHANGELOG: $CHANGELOG_FILE${NC}"
echo ""

# ============================================
# Step 5: 更新 bin/current 符号链接
# ============================================
echo "Step 5: 更新 bin/current 符号链接..."

CURRENT_LINK="/brain/infrastructure/hooks/bin/current"
TARGET_PATH="../releases/$VERSION/bin"

# 删除旧链接
if [ -L "$CURRENT_LINK" ]; then
    rm "$CURRENT_LINK"
fi

# 创建新链接
ln -s "$TARGET_PATH" "$CURRENT_LINK"

echo -e "${GREEN}✓ $CURRENT_LINK -> $TARGET_PATH${NC}"
echo ""

# ============================================
# Step 6: 创建 Git tag (可选)
# ============================================
echo "Step 6: 创建 Git tag (可选)..."

if git rev-parse --git-dir > /dev/null 2>&1; then
    TAG_NAME="hooks-v2-$VERSION"

    if git tag -a "$TAG_NAME" -m "Hooks V2 Release $VERSION" 2>/dev/null; then
        echo -e "${GREEN}✓ Git tag: $TAG_NAME${NC}"
    else
        echo -e "${YELLOW}⚠ Git tag 已存在或创建失败${NC}"
    fi
else
    echo -e "${YELLOW}⚠ 不是 git 仓库，跳过 tag${NC}"
fi

echo ""

# ============================================
# 完成
# ============================================
echo "========================================"
echo -e "${GREEN}✅ 发布完成！${NC}"
echo "========================================"
echo ""
echo "发布版本: $VERSION"
echo "产物位置: $RELEASE_DIR"
echo "Changelog: $CHANGELOG_FILE"
echo "Current link: $CURRENT_LINK"
echo ""
echo "下一步:"
echo "  1. 查看 changelog: cat $CHANGELOG_FILE"
echo "  2. 部署到 dev: bash scripts/deploy.sh $VERSION dev"
echo "  3. 部署到所有: bash scripts/deploy.sh $VERSION all"
echo ""
