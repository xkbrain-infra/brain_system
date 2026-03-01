#!/bin/bash
# Hooks 系统演示脚本
# 展示完整的 开发-编译-测试-发布-部署 流程

set -e

HOOK_ROOT="/brain/infrastructure/service/agent_abilities"

# 颜色输出
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

clear

echo "╔════════════════════════════════════════════════════════╗"
echo "║                                                        ║"
echo "║        Hooks 系统 V2.0 - 完整流程演示                   ║"
echo "║                                                        ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

read -p "按 Enter 开始演示..."

# ============================================================
# 阶段 1: 开发
# ============================================================

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}阶段 1: 开发阶段${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo "📝 场景：为 Dev 角色添加一个新规则 - 禁止使用 console.log"
echo ""

echo "创建规则文件: rules/roles/dev/demo_no_console.yaml"
cat > "$HOOK_ROOT/rules/roles/dev/demo_no_console.yaml" << 'EOF'
gates:
  G-DEMO-NO-CONSOLE:
    name: Demo - No Console Log
    applies_to: [write]
    rule: 禁止提交包含 console.log 的代码

    enforcement:
      stage: pre_tool_use
      method: python_inline
      priority: MEDIUM

      triggers:
        tools: [Write, Edit]

      patterns:
        console_log:
          - pattern: "console\\.log"
            message: "禁止使用 console.log"

      warn_message: |
        ⚠️ 代码质量检查

        检测到 console.log 语句。

        请在提交前移除调试代码。
EOF

echo -e "${GREEN}✓${NC} 规则文件创建完成"
echo ""

read -p "按 Enter 继续到编译阶段..."

# ============================================================
# 阶段 2: 编译
# ============================================================

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}阶段 2: 编译阶段${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo "执行: bash scripts/build_v2.sh"
echo ""

# 创建必要的目录
mkdir -p "$HOOK_ROOT/rules/roles/pmo"
mkdir -p "$HOOK_ROOT/rules/roles/architect"
mkdir -p "$HOOK_ROOT/rules/roles/qa"

# 执行编译（静默模式，只显示关键输出）
cd "$HOOK_ROOT"
bash scripts/build_v2.sh 2>/dev/null | grep -E "(Step|✓|✅)" || true

echo ""
echo "查看编译产物:"
echo ""
echo "  build/"
echo "  ├── bin/"
ls -1 "$HOOK_ROOT/build/bin/" 2>/dev/null | sed 's/^/  │   ├── /' || echo "  │   (文件未生成)"
echo "  └── configs/"
echo "      ├── settings.global.json"
ls -1 "$HOOK_ROOT/build/configs/settings.roles/" 2>/dev/null | sed 's/^/      └── /' || echo "      (文件未生成)"

echo ""
read -p "按 Enter 查看 Dev 角色的 settings.json..."

echo ""
echo "settings.dev.json 内容："
echo ""
cat "$HOOK_ROOT/build/configs/settings.roles/settings.dev.json" 2>/dev/null | jq . || echo "文件不存在"

echo ""
read -p "按 Enter 继续到测试阶段..."

# ============================================================
# 阶段 3: 测试
# ============================================================

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}阶段 3: 测试阶段${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo "测试场景 1: 提交包含 console.log 的代码（应该警告）"
echo ""

TEST_INPUT='{
  "hookEventName": "PreToolUse",
  "toolName": "Write",
  "toolInput": {
    "file_path": "/test/demo.js",
    "content": "function test() {\n  console.log(\"debug\");\n  return 123;\n}"
  }
}'

echo "输入:"
echo "$TEST_INPUT" | jq .
echo ""

if [ -f "$HOOK_ROOT/build/bin/pre_tool_use" ]; then
    echo "输出:"
    echo "$TEST_INPUT" | "$HOOK_ROOT/build/bin/pre_tool_use" 2>/dev/null | jq . || echo "执行失败"
else
    echo -e "${YELLOW}⚠${NC}  Hook 文件不存在，跳过测试"
fi

echo ""
read -p "按 Enter 继续..."

echo ""
echo "测试场景 2: 提交正常代码（应该通过）"
echo ""

TEST_INPUT_PASS='{
  "hookEventName": "PreToolUse",
  "toolName": "Write",
  "toolInput": {
    "file_path": "/test/demo.js",
    "content": "function test() {\n  return 123;\n}"
  }
}'

echo "输入:"
echo "$TEST_INPUT_PASS" | jq .
echo ""

if [ -f "$HOOK_ROOT/build/bin/pre_tool_use" ]; then
    echo "输出:"
    echo "$TEST_INPUT_PASS" | "$HOOK_ROOT/build/bin/pre_tool_use" 2>/dev/null | jq . || echo "执行失败"
else
    echo -e "${YELLOW}⚠${NC}  Hook 文件不存在，跳过测试"
fi

echo ""
read -p "按 Enter 继续到发布阶段..."

# ============================================================
# 阶段 4: 发布
# ============================================================

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}阶段 4: 发布阶段${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

DEMO_VERSION="v2.0.0-demo"

echo "执行: bash scripts/release.sh $DEMO_VERSION"
echo ""

# 创建发布（简化版）
mkdir -p "$HOOK_ROOT/releases/$DEMO_VERSION"
cp -r "$HOOK_ROOT/build"/* "$HOOK_ROOT/releases/$DEMO_VERSION/" 2>/dev/null || true

echo -e "${GREEN}✓${NC} 发布完成"
echo ""

echo "发布产物:"
echo ""
echo "  releases/$DEMO_VERSION/"
ls -1 "$HOOK_ROOT/releases/$DEMO_VERSION/" 2>/dev/null | sed 's/^/    /' || echo "    (空)"

echo ""
read -p "按 Enter 继续到部署阶段..."

# ============================================================
# 阶段 5: 部署
# ============================================================

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}阶段 5: 部署阶段${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo "部署到 Dev agents..."
echo ""

echo "目标 agents:"
echo "  - agent_system_dev1"
echo "  - agent_system_dev2"
echo ""

echo -e "${YELLOW}注意${NC}: 这是演示，实际部署使用:"
echo "  bash scripts/deploy.sh $DEMO_VERSION dev"
echo ""

# ============================================================
# 总结
# ============================================================

read -p "按 Enter 查看总结..."

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}演示总结${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo "✅ 完成了完整的工作流:"
echo ""
echo "  1. 开发    → 创建规则文件 (rules/roles/dev/demo_no_console.yaml)"
echo "  2. 编译    → 生成 bin + settings.json (build/)"
echo "  3. 测试    → 验证规则生效"
echo "  4. 发布    → 打包版本 (releases/$DEMO_VERSION/)"
echo "  5. 部署    → 部署到 agents (按角色)"
echo ""

echo "🎯 关键特性:"
echo ""
echo "  ✅ 规则和代码分离 (YAML + Python)"
echo "  ✅ 编译产物清晰 (bin/ + configs/)"
echo "  ✅ 角色化配置 (PMO/Architect/Dev/QA)"
echo "  ✅ 版本管理 (releases/)"
echo "  ✅ 两层过滤 (Matcher + Triggers)"
echo ""

echo "📚 相关文档:"
echo ""
echo "  - README_V2.md - 系统概览"
echo "  - ARCHITECTURE.md - 架构设计"
echo "  - WORKFLOW.md - 完整工作流"
echo ""

echo "🚀 下一步:"
echo ""
echo "  1. 查看文档: cat README_V2.md"
echo "  2. 实际编译: bash scripts/build_v2.sh"
echo "  3. 运行测试: bash scripts/test.sh"
echo "  4. 发布版本: bash scripts/release.sh v2.1.0"
echo "  5. 部署: bash scripts/deploy.sh v2.1.0 dev"
echo ""

# 清理演示文件
echo ""
read -p "按 Enter 清理演示文件..."

rm -f "$HOOK_ROOT/rules/roles/dev/demo_no_console.yaml"
rm -rf "$HOOK_ROOT/releases/$DEMO_VERSION"

echo ""
echo -e "${GREEN}✅ 演示完成！${NC}"
echo ""
