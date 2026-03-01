#!/bin/bash
# Hook 构建系统
# 源码: src/base/hooks/ (平铺结构，无版本目录)
# 产出: bin/hooks/{version}/ → 部署到 /brain/base/hooks/

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# build/scripts/hooks/ → build/ → agent_abilities/
HOOK_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$HOOK_ROOT"

SRC_HOOKS="src/base/hooks"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "========================================"
echo "Brain Hooks Build System"
echo "========================================"
echo ""

# 解析参数
VERSION=""
SKIP_TEST=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --version)
            VERSION="$2"
            shift 2
            ;;
        --skip-test)
            SKIP_TEST=true
            shift
            ;;
        *)
            echo -e "${RED}未知参数: $1${NC}"
            exit 1
            ;;
    esac
done

if [ -z "$VERSION" ]; then
    VERSION=$(grep '^version:' build/version.yaml 2>/dev/null | sed 's/version: *"\?\([^"]*\)"\?/\1/' | tr -d '"')
fi

echo -e "${YELLOW}构建版本: $VERSION${NC}"
echo ""

# ============================================
# Step 1: 验证 src 结构完整性
# ============================================
echo "Step 1: 验证 $SRC_HOOKS/ 结构..."

REQUIRED_FILES=(
    "tool_validation/handler.py"
    "session/handler.py"
    "checkers/audit_logger/logger.py"
    "checkers/path_checker/checker.py"
    "checkers/file_org_checker/checker.py"
    "lep/engine.py"
    "lep/checkers.py"
    "utils/io_helper.py"
    "pre_tool_use"
    "post_tool_use"
    "session_start"
    "session_end"
    "user_prompt_submit"
)

for f in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$SRC_HOOKS/$f" ]; then
        echo -e "${RED}✗ 缺少: $SRC_HOOKS/$f${NC}"
        exit 1
    fi
done

echo -e "${GREEN}✓ src/ 结构完整${NC}"
echo ""

# ============================================
# Step 2: Python 语法检查
# ============================================
echo "Step 2: Python 语法检查..."

error_count=0
while IFS= read -r pyfile; do
    if ! python3 -m py_compile "$pyfile" 2>/dev/null; then
        echo -e "${RED}✗ 语法错误: $pyfile${NC}"
        ((error_count++)) || true
    fi
done < <(find "$SRC_HOOKS" -name "*.py" -type f)

if [ $error_count -gt 0 ]; then
    echo -e "${RED}发现 $error_count 个语法错误${NC}"
    exit 1
fi

echo -e "${GREEN}✓ 所有 Python 文件语法正确${NC}"
echo ""

# ============================================
# Step 3: 生成 bin/ 部署包
# ============================================
echo "Step 3: 生成 bin/hooks/$VERSION/ 部署包..."

BIN_DIR="bin/hooks/$VERSION"
rm -rf "$BIN_DIR"
mkdir -p "$BIN_DIR"

# 3a. 生成 entry 脚本（部署后路径为 /brain/base/hooks/）
HOOK_ENTRIES=(
    "pre_tool_use:tool_validation:handle_pre_tool_use"
    "post_tool_use:tool_validation:handle_post_tool_use"
    "session_start:session:handle_session_start"
    "session_end:session:handle_session_end"
    "user_prompt_submit:session:handle_user_prompt_submit"
)

for entry in "${HOOK_ENTRIES[@]}"; do
    IFS=':' read -r hook_name handler_type handler_func <<< "$entry"

    cat > "$BIN_DIR/$hook_name" <<PYEOF
#!/usr/bin/env python3
"""$hook_name Hook - $VERSION 入口 (自动生成)"""
import os
import sys

# 优先使用已有的 HOOK_ROOT（测试时可覆盖），否则默认部署路径
HOOK_ROOT = os.environ.get("HOOK_ROOT", "/brain/base/hooks")
os.environ["HOOK_ROOT"] = HOOK_ROOT

sys.path.insert(0, os.path.join(HOOK_ROOT, "tool_validation"))
sys.path.insert(0, os.path.join(HOOK_ROOT, "session"))
sys.path.insert(0, os.path.join(HOOK_ROOT, "checkers", "audit_logger"))
sys.path.insert(0, os.path.join(HOOK_ROOT, "utils"))
sys.path.insert(0, os.path.join(HOOK_ROOT, "lep"))

from ${handler_type}.handler import $handler_func

if __name__ == "__main__":
    $handler_func()
PYEOF

    chmod +x "$BIN_DIR/$hook_name"
    echo -e "  ${GREEN}✓${NC} $hook_name"
done

# 3b. 复制源码模块（平铺结构直接复制）
for mod in lep utils rules; do
    if [ -d "$SRC_HOOKS/$mod" ]; then
        cp -r "$SRC_HOOKS/$mod" "$BIN_DIR/"
    fi
done

# tool_validation / session 已在 src 顶层，直接复制
for mod in tool_validation session; do
    cp -r "$SRC_HOOKS/$mod" "$BIN_DIR/"
done

# checkers
cp -r "$SRC_HOOKS/checkers" "$BIN_DIR/"

# overrides（agent-specific hook overrides）
if [ -d "$SRC_HOOKS/overrides" ]; then
    cp -r "$SRC_HOOKS/overrides" "$BIN_DIR/"
fi

# 清理 __pycache__
find "$BIN_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

echo ""

# ============================================
# Step 4: 更新 current symlink
# ============================================
echo "Step 4: 更新 bin/hooks/current symlink..."

rm -f "bin/hooks/current"
ln -s "$VERSION" "bin/hooks/current"
echo -e "${GREEN}✓ bin/hooks/current -> $VERSION${NC}"
echo ""

# ============================================
# Step 5: 运行集成测试
# ============================================
if [ "$SKIP_TEST" = false ]; then
    echo "Step 5: 运行集成测试..."

    # 快速冒烟测试：block 受保护路径
    # exit code 2 = block, 检测 permissionDecision=deny
    EXIT_CODE=0
    RESULT=$(echo '{"tool_name":"Write","tool_input":{"file_path":"/brain/base/spec/test.txt","content":"x"}}' | \
        HOOK_ROOT="$BIN_DIR" python3 "$BIN_DIR/pre_tool_use" 2>/dev/null) || EXIT_CODE=$?

    if [ "$EXIT_CODE" -eq 2 ] && echo "$RESULT" | grep -q '"permissionDecision": "deny"'; then
        echo -e "  ${GREEN}✓${NC} pre_tool_use: 受保护路径被拦截 (exit=$EXIT_CODE, deny)"
    else
        echo -e "${RED}✗ pre_tool_use: 受保护路径未被拦截 (exit=$EXIT_CODE)${NC}"
        echo "  output: $RESULT"
        exit 1
    fi

    # 合法路径应通过 (exit code 0)
    EXIT_CODE=0
    RESULT=$(echo '{"tool_name":"Write","tool_input":{"file_path":"/brain/groups/test.txt","content":"x"}}' | \
        HOOK_ROOT="$BIN_DIR" python3 "$BIN_DIR/pre_tool_use" 2>/dev/null) || EXIT_CODE=$?

    if [ "$EXIT_CODE" -eq 2 ]; then
        echo -e "${RED}✗ pre_tool_use: 合法路径被误拦截 (exit=$EXIT_CODE)${NC}"
        exit 1
    else
        echo -e "  ${GREEN}✓${NC} pre_tool_use: 合法路径通过 (exit=$EXIT_CODE)"
    fi

    echo -e "${GREEN}✓ 集成测试通过${NC}"
    echo ""
fi

# ============================================
# Step 6: 构建报告
# ============================================
echo "========================================"
echo -e "${GREEN}✅ 构建完成${NC}"
echo "========================================"
echo ""
echo "构建信息:"
echo "  版本: $VERSION"
echo "  源码: $SRC_HOOKS/"
echo "  产出: $BIN_DIR/"
echo "  入口: $(ls -1 "$BIN_DIR"/{pre,post,session,user}* 2>/dev/null | wc -l) 个"
echo ""
