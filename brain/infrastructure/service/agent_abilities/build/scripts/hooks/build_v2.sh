#!/bin/bash
# Hooks 编译脚本 V2
# 功能：编译源码 → 生成 bin 和 settings.json 模板

set -e  # 遇到错误立即退出

HOOK_ROOT="/brain/infrastructure/service/agent_abilities"
SRC_DIR="$HOOK_ROOT/src"
RULES_DIR="$HOOK_ROOT/rules"
BUILD_DIR="$HOOK_ROOT/build"
SCRIPTS_DIR="$HOOK_ROOT/scripts"

# 颜色输出
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================"
echo "Hooks Build System V2"
echo "========================================"
echo ""

# Step 1: 清理旧产物
echo "Step 1: 清理旧产物..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"/{bin,configs/settings.roles}
echo -e "${GREEN}✓${NC} 清理完成"
echo ""

# Step 2: 语法检查
echo "Step 2: Python 语法检查..."
SYNTAX_ERROR=0

for py_file in $(find "$SRC_DIR" -name "*.py"); do
    if ! python3 -m py_compile "$py_file" 2>/dev/null; then
        echo -e "${RED}✗${NC} 语法错误: $py_file"
        SYNTAX_ERROR=1
    fi
done

if [ $SYNTAX_ERROR -eq 1 ]; then
    echo -e "${RED}✗${NC} 构建失败：存在语法错误"
    exit 1
fi

echo -e "${GREEN}✓${NC} 所有 Python 文件语法正确"
echo ""

# Step 3: 生成 bin 可执行文件
echo "Step 3: 生成 bin 可执行文件..."

# 查找当前版本
if [ -L "$SRC_DIR/handlers/tool_validation/current" ]; then
    HANDLER_VERSION=$(readlink "$SRC_DIR/handlers/tool_validation/current")
else
    HANDLER_VERSION="v1"
fi

echo "使用 Handler 版本: $HANDLER_VERSION"

# 生成 pre_tool_use
cat > "$BUILD_DIR/bin/pre_tool_use" << 'EOF'
#!/usr/bin/env python3
"""pre_tool_use Hook - 编译产物"""
import sys
import os

HOOK_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(HOOK_ROOT, "src", "handlers", "tool_validation", "current", "python"))

from handler import handle_pre_tool_use

if __name__ == "__main__":
    handle_pre_tool_use()
EOF

chmod +x "$BUILD_DIR/bin/pre_tool_use"

# 生成 post_tool_use
cat > "$BUILD_DIR/bin/post_tool_use" << 'EOF'
#!/usr/bin/env python3
"""post_tool_use Hook - 编译产物"""
import sys
import os

HOOK_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(HOOK_ROOT, "src", "handlers", "tool_validation", "current", "python"))

from handler import handle_post_tool_use

if __name__ == "__main__":
    handle_post_tool_use()
EOF

chmod +x "$BUILD_DIR/bin/post_tool_use"

echo -e "${GREEN}✓${NC} 生成了 $(ls $BUILD_DIR/bin | wc -l) 个可执行文件"
echo ""

# Step 4: 合并规则
echo "Step 4: 合并规则（全局 + 角色）..."

python3 "$SCRIPTS_DIR/merge_rules.py"

echo -e "${GREEN}✓${NC} 规则合并完成"
echo ""

# Step 5: 生成 settings.json 模板
echo "Step 5: 生成 settings.json 模板..."

python3 "$SCRIPTS_DIR/generate_settings.py"

echo -e "${GREEN}✓${NC} 生成了 $(ls $BUILD_DIR/configs/settings.roles/*.json 2>/dev/null | wc -l) 个角色配置"
echo ""

# Step 6: 运行单元测试（可选）
if [ "$RUN_TESTS" = "1" ]; then
    echo "Step 6: 运行单元测试..."
    bash "$SCRIPTS_DIR/test.sh"
else
    echo "Step 6: 跳过测试（设置 RUN_TESTS=1 启用）"
fi

echo ""
echo "========================================"
echo -e "${GREEN}✅ 构建成功！${NC}"
echo "========================================"
echo ""
echo "产物位置："
echo "  - 可执行文件: $BUILD_DIR/bin/"
echo "  - 全局配置: $BUILD_DIR/configs/settings.global.json"
echo "  - 角色配置: $BUILD_DIR/configs/settings.roles/"
echo ""
echo "下一步："
echo "  1. 测试: bash scripts/test.sh"
echo "  2. 发布: bash scripts/release.sh v2.1.0"
echo "  3. 部署: bash scripts/deploy.sh v2.1.0"
echo ""
