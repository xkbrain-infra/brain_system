#!/bin/bash
# Task Manager Release — 编译 + 快照源码 + 版本化发布
#
# 用法:
#   bash scripts/release.sh v1.0.0              # 编译并创建 release
#   bash scripts/release.sh v1.0.0 --activate   # 创建并激活 bin/current
#   bash scripts/release.sh --rollback v1.0.0   # 回滚到旧版本
#   bash scripts/release.sh --list              # 列出所有版本
#
# Release 目录结构:
#   releases/v1.0.0/
#   ├── bin/
#   │   └── service-task_manager   ← 编译产物
#   ├── src/                       ← 源码快照 (immutable)
#   └── VERSION                    ← 版本元信息

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RELEASES_DIR="$ROOT/releases"
BIN_NAME="service-task_manager"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
log_err()  { echo -e "${RED}[ERR]${NC} $*"; }
log_step() { echo -e "${YELLOW}[$1]${NC} $2"; }

# --- List mode ---
if [ "${1:-}" = "--list" ]; then
    echo "已发布版本:"
    if [ -d "$RELEASES_DIR" ]; then
        for d in "$RELEASES_DIR"/v*/; do
            [ -d "$d" ] || continue
            ver=$(basename "$d")
            if [ -f "$d/VERSION" ]; then
                created=$(grep '^created:' "$d/VERSION" | cut -d' ' -f2-)
                commit=$(grep '^source_commit:' "$d/VERSION" | cut -d' ' -f2-)
                echo "  $ver  (commit: $commit, created: $created)"
            else
                echo "  $ver  (no VERSION file)"
            fi
        done
    else
        echo "  (无)"
    fi
    CURRENT=$(readlink "$ROOT/bin/current" 2>/dev/null || echo "none")
    echo "当前激活: $CURRENT"
    exit 0
fi

# --- Rollback mode ---
if [ "${1:-}" = "--rollback" ]; then
    TARGET="${2:?用法: release.sh --rollback <version>}"
    RELEASE_DIR="$RELEASES_DIR/$TARGET"
    if [ ! -x "$RELEASE_DIR/bin/$BIN_NAME" ]; then
        log_err "Release $TARGET 不存在或不完整"
        exit 1
    fi
    OLD=$(readlink "$ROOT/bin/current" 2>/dev/null || echo "none")
    ln -sfn "../releases/$TARGET/bin" "$ROOT/bin/current"
    log_ok "回滚完成: bin/current -> releases/$TARGET/bin"
    log_ok "旧版本: $OLD"
    exit 0
fi

# --- Create release ---
VERSION="${1:?用法: release.sh <version> [--activate]}"
ACTIVATE=false
[ "${2:-}" = "--activate" ] && ACTIVATE=true

RELEASE_DIR="$RELEASES_DIR/$VERSION"

echo "========================================"
echo " Task Manager Release: $VERSION"
echo "========================================"

# Step 1: 检查版本是否已存在 (immutable)
log_step 1 "预检查"
if [ -d "$RELEASE_DIR" ]; then
    log_err "Release $VERSION 已存在，已发布版本不可覆盖"
    echo "  如需重建，先删除: rm -rf $RELEASE_DIR"
    exit 1
fi

# Step 2: 编译
log_step 2 "编译 src/ -> build/"
cd "$ROOT"
make clean
make
if [ ! -x "build/$BIN_NAME" ]; then
    log_err "编译失败: build/$BIN_NAME 不存在"
    exit 1
fi
log_ok "编译成功"

# Step 3: 创建 release 目录
log_step 3 "创建 release 目录"
mkdir -p "$RELEASE_DIR/bin"
mkdir -p "$RELEASE_DIR/src"

# Step 4: 复制编译产物
log_step 4 "复制编译产物到 releases/$VERSION/bin/"
cp "build/$BIN_NAME" "$RELEASE_DIR/bin/$BIN_NAME"
chmod +x "$RELEASE_DIR/bin/$BIN_NAME"
log_ok "bin/$BIN_NAME 已复制"

# Step 5: 快照源码
log_step 5 "快照源码到 releases/$VERSION/src/"
cp -r src/*.c src/*.h "$RELEASE_DIR/src/"
log_ok "源码快照完成 ($(ls "$RELEASE_DIR/src/" | wc -l) 个文件)"

# Step 6: 复制 Makefile (可复现编译)
cp Makefile "$RELEASE_DIR/Makefile"

# Step 7: 写 VERSION 文件
log_step 6 "写入版本信息"
cat > "$RELEASE_DIR/VERSION" <<EOF
version: $VERSION
created: $(date -Iseconds)
source_commit: $(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
binary_hash: $(sha256sum "$RELEASE_DIR/bin/$BIN_NAME" | cut -d' ' -f1)
src_files:
$(cd "$RELEASE_DIR/src" && for f in *; do echo "  $f: $(sha256sum "$f" | cut -d' ' -f1)"; done)
EOF
log_ok "VERSION 文件已写入"

# Step 8: 验证 release 完整性
log_step 7 "验证 release 完整性"
ERRORS=0

if [ ! -x "$RELEASE_DIR/bin/$BIN_NAME" ]; then
    log_err "二进制缺失"
    ERRORS=$((ERRORS+1))
fi

for src_file in task_manager.h task_store.c spec_store.c validator.c service_task_manager.c; do
    if [ ! -f "$RELEASE_DIR/src/$src_file" ]; then
        log_err "源码快照缺失: $src_file"
        ERRORS=$((ERRORS+1))
    fi
done

# 校验二进制是 ELF 可执行 (检查 magic bytes)
if head -c4 "$RELEASE_DIR/bin/$BIN_NAME" | grep -q "ELF"; then
    log_ok "二进制格式正确 (ELF)"
fi

if [ $ERRORS -gt 0 ]; then
    log_err "验证失败 ($ERRORS 个错误)"
    exit 1
fi
log_ok "验证通过"

# Step 9: 激活
if $ACTIVATE; then
    log_step 8 "激活 release"
    mkdir -p "$ROOT/bin"
    OLD=$(readlink "$ROOT/bin/current" 2>/dev/null || echo "none")
    ln -sfn "../releases/$VERSION/bin" "$ROOT/bin/current"
    log_ok "bin/current -> releases/$VERSION/bin"
    [ "$OLD" != "none" ] && log_ok "旧版本: $OLD"
else
    log_step 8 "跳过激活 (加 --activate 参数启用)"
    echo "  手动激活: ln -sfn ../releases/$VERSION/bin $ROOT/bin/current"
fi

# Summary
echo ""
echo "========================================"
echo -e "${GREEN}Release $VERSION 创建成功${NC}"
echo "========================================"
echo ""
echo "目录: $RELEASE_DIR"
echo "文件数: $(find "$RELEASE_DIR" -type f | wc -l)"
echo ""
cat "$RELEASE_DIR/VERSION"
