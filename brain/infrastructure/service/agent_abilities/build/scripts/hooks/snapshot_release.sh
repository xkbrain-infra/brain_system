#!/bin/bash
# Hooks Snapshot Release - 创建代码快照发布
#
# 将 src/ 完整快照到 releases/{version}/，保持内部路径深度不变，
# 使得所有 handler.py 中的相对路径计算自动生效。
#
# 用法:
#   bash scripts/snapshot_release.sh v2.2.0          # 创建 release
#   bash scripts/snapshot_release.sh v2.2.0 --activate  # 创建并切换 bin/current
#   bash scripts/snapshot_release.sh --rollback v2.1.0   # 回滚到旧版本
#
# Release 目录结构:
#   releases/v2.2.0/
#   ├── bin/v2/            ← 入口脚本 (保持 3 层深度)
#   ├── src/               ← 代码快照 (cp -rL 解析 symlink)
#   │   ├── handlers/
#   │   ├── checkers/
#   │   ├── lep/           ← 包含编译好的 lep_check binary
#   │   └── utils/
#   ├── rules -> ../../rules  ← 共享规则 (配置，非代码)
#   └── VERSION

set -euo pipefail

HOOKS_ROOT="/brain/infrastructure/service/agent_abilities/hooks"
RELEASES_DIR="$HOOKS_ROOT/releases"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_ok()   { echo -e "${GREEN}✓${NC} $*"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $*"; }
log_err()  { echo -e "${RED}✗${NC} $*"; }
log_step() { echo -e "\n${YELLOW}[$1]${NC} $2"; }

# --- Rollback mode ---
if [ "${1:-}" = "--rollback" ]; then
    TARGET="${2:?用法: snapshot_release.sh --rollback <version>}"
    RELEASE_DIR="$RELEASES_DIR/$TARGET"
    if [ ! -d "$RELEASE_DIR/bin/v2" ]; then
        log_err "Release $TARGET 不存在或不完整"
        exit 1
    fi
    OLD=$(readlink -f "$HOOKS_ROOT/bin/current" 2>/dev/null || echo "none")
    ln -sfn "../releases/$TARGET/bin/v2" "$HOOKS_ROOT/bin/current"
    log_ok "回滚完成: bin/current → releases/$TARGET/bin/v2"
    log_ok "旧版本: $OLD"
    exit 0
fi

# --- Create release ---
VERSION="${1:?用法: snapshot_release.sh <version> [--activate]}"
ACTIVATE=false
[ "${2:-}" = "--activate" ] && ACTIVATE=true

RELEASE_DIR="$RELEASES_DIR/$VERSION"

echo "========================================"
echo " Hooks Snapshot Release: $VERSION"
echo "========================================"

# Step 1: Pre-flight checks
log_step 1 "预检查"

if [ -d "$RELEASE_DIR/src" ]; then
    log_err "Release $VERSION 已存在: $RELEASE_DIR"
    echo "  删除后重试: rm -rf $RELEASE_DIR"
    exit 1
fi

# Verify source exists
for dir in src/handlers src/checkers src/lep src/utils bin/v2; do
    if [ ! -d "$HOOKS_ROOT/$dir" ]; then
        log_err "源目录不存在: $HOOKS_ROOT/$dir"
        exit 1
    fi
done

# Verify lep_check binary
if [ ! -x "$HOOKS_ROOT/src/lep/lep_check" ]; then
    log_warn "lep_check 二进制不存在，尝试编译..."
    gcc -O2 -o "$HOOKS_ROOT/src/lep/lep_check" "$HOOKS_ROOT/src/lep/lep_check.c"
    log_ok "编译成功"
fi

log_ok "预检查通过"

# Step 2: Create release directory
log_step 2 "创建 release 目录"
mkdir -p "$RELEASE_DIR"

# Step 3: Snapshot src/ (resolve symlinks with cp -rL)
log_step 3 "快照 src/ (解析 symlinks)"
cp -rL "$HOOKS_ROOT/src" "$RELEASE_DIR/src"
# Remove __pycache__
find "$RELEASE_DIR/src" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
log_ok "src/ 快照完成"

# Step 4: Copy bin/v2 entry scripts
log_step 4 "复制入口脚本 bin/v2/"
mkdir -p "$RELEASE_DIR/bin"
cp -r "$HOOKS_ROOT/bin/v2" "$RELEASE_DIR/bin/v2"
chmod +x "$RELEASE_DIR/bin/v2"/*
log_ok "入口脚本复制完成"

# Step 5: Symlink shared rules (configuration, not code)
log_step 5 "链接共享规则"
ln -sfn "../../rules" "$RELEASE_DIR/rules"
log_ok "rules → ../../rules"

# Step 6: Write VERSION file
log_step 6 "写入版本信息"
cat > "$RELEASE_DIR/VERSION" <<EOF
version: $VERSION
created: $(date -Iseconds)
source_commit: $(cd "$HOOKS_ROOT" && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
lep_check_hash: $(sha256sum "$RELEASE_DIR/src/lep/lep_check" 2>/dev/null | cut -d' ' -f1 || echo "none")
handler_hash: $(sha256sum "$RELEASE_DIR/src/handlers/tool_validation/v1/python/handler.py" 2>/dev/null | cut -d' ' -f1 || echo "none")
role_scope_hash: $(sha256sum "$RELEASE_DIR/src/lep/role_scope.py" 2>/dev/null | cut -d' ' -f1 || echo "none")
EOF
log_ok "VERSION 文件已写入"

# Step 7: Verify release integrity
log_step 7 "验证 release 完整性"
ERRORS=0

# Check entry scripts resolve correctly
for script in pre_tool_use post_tool_use; do
    if [ ! -x "$RELEASE_DIR/bin/v2/$script" ]; then
        log_err "入口脚本缺失: bin/v2/$script"
        ERRORS=$((ERRORS+1))
    fi
done

# Check handler exists
HANDLER="$RELEASE_DIR/src/handlers/tool_validation/v1/python/handler.py"
if [ ! -f "$HANDLER" ]; then
    log_err "handler.py 缺失"
    ERRORS=$((ERRORS+1))
fi

# Check lep_check binary
if [ ! -x "$RELEASE_DIR/src/lep/lep_check" ]; then
    log_err "lep_check 二进制缺失"
    ERRORS=$((ERRORS+1))
fi

# Check role_scope module
if [ ! -f "$RELEASE_DIR/src/lep/role_scope.py" ]; then
    log_err "role_scope.py 缺失"
    ERRORS=$((ERRORS+1))
fi

# Check rules symlink resolves
if [ ! -d "$RELEASE_DIR/rules/roles" ]; then
    log_err "rules 链接无效"
    ERRORS=$((ERRORS+1))
fi

# Quick smoke test: entry script can import handler
if python3 -c "
import sys, os
sys.path.insert(0, '$RELEASE_DIR/src/handlers/tool_validation/v1/python')
import handler
print('import OK')
" 2>/dev/null | grep -q "import OK"; then
    log_ok "import 测试通过"
else
    log_err "import 测试失败"
    ERRORS=$((ERRORS+1))
fi

if [ $ERRORS -gt 0 ]; then
    log_err "验证失败 ($ERRORS 个错误)，release 可能不完整"
    exit 1
fi
log_ok "验证通过"

# Step 8: Activate (optional)
if $ACTIVATE; then
    log_step 8 "激活 release"
    OLD=$(readlink "$HOOKS_ROOT/bin/current" 2>/dev/null || echo "none")
    ln -sfn "../releases/$VERSION/bin/v2" "$HOOKS_ROOT/bin/current"
    log_ok "bin/current → releases/$VERSION/bin/v2"
    log_ok "旧链接: $OLD"
else
    log_step 8 "跳过激活 (使用 --activate 参数启用)"
    echo "  手动激活: ln -sfn ../releases/$VERSION/bin/v2 $HOOKS_ROOT/bin/current"
fi

# Summary
echo ""
echo "========================================"
echo -e "${GREEN}✅ Release $VERSION 创建成功${NC}"
echo "========================================"
echo ""
echo "目录: $RELEASE_DIR"
echo "文件数: $(find "$RELEASE_DIR" -type f | wc -l)"
echo "大小: $(du -sh "$RELEASE_DIR" | cut -f1)"
echo ""
echo "使用方法:"
echo "  激活:  ln -sfn ../releases/$VERSION/bin/v2 $HOOKS_ROOT/bin/current"
echo "  回滚:  bash scripts/snapshot_release.sh --rollback <old_version>"
echo "  锁定:  在 agents_registry.yaml 中设置 hooks_version: $VERSION"
echo ""
cat "$RELEASE_DIR/VERSION"
