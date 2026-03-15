#!/bin/bash
# build_bin.sh — 编译和部署 brain 二进制产物
#
# 职责：
#   - 编译 C 二进制（lep_check、mcp-brain_ipc_c）
#   - 更新 /brain/bin/ 下的分类 symlinks
#
# 不在此脚本范围内（由 publish_base.sh 负责）：
#   - spec / workflow / knowledge / skill / hooks Python 内容的发布
#
# 用法:
#   build_bin.sh build  [hooks|mcp|all]   编译二进制
#   build_bin.sh install [mcp]            安装已编译的 MCP 运行时入口
#   build_bin.sh deploy [hooks|mcp|all]   编译 + 部署到 /brain/bin/
#   build_bin.sh links                     刷新 /brain/bin/ 下所有 symlinks
#   build_bin.sh verify                    检查 /brain/bin/mcp/ symlinks 是否有效
#
# 示例:
#   build_bin.sh build mcp
#   build_bin.sh deploy mcp
#   build_bin.sh links

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Live build entrypoint still operates on the canonical source tree.
PROJECT_ROOT="/xkagent_infra/groups/brain/projects/base"

RED='\033[31m'; GREEN='\033[32m'; YELLOW='\033[33m'; CYAN='\033[36m'; BOLD='\033[1m'; RESET='\033[0m'
log()  { echo -e "${CYAN}[build_bin]${RESET} $1"; }
ok()   { echo -e "${GREEN}[build_bin] ✓${RESET} $1"; }
warn() { echo -e "${YELLOW}[build_bin] ⚠${RESET} $1"; }
fail() { echo -e "${RED}[build_bin] ✗${RESET} $1"; exit 1; }

# ─── 路径配置 ────────────────────────────────────────────────────────
HOOKS_SRC="$PROJECT_ROOT/hooks/lep"        # lep_check.c
MCP_SRC="$PROJECT_ROOT/mcp/brain_ipc_c"    # MCP C 源码

BRAIN_BIN="/brain/bin"
BRAIN_BIN_MCP="/brain/bin/mcp"
BRAIN_BIN_HOOKS="/brain/bin/hooks"
BRAIN_SERVICES="/brain/infrastructure/service"

# ─── _backup_live_target ─────────────────────────────────────────────
_backup_live_target() {
    local target="$1"
    local backup_root="$2"

    [ -e "$target" ] || [ -L "$target" ] || return 0

    mkdir -p "$backup_root"
    cp -a "$target" "$backup_root/"
}

# ─── _update_global_bin_symlinks ─────────────────────────────────────
# 扫描所有 service/*/bin/* 可执行文件，按类型分类放到 /brain/bin/ 子目录
#
# 分类规则：
#   *_mcp_server 或 mcp-*   → /brain/bin/mcp/<name>
#   *hook* 或 *_hook        → /brain/bin/hooks/<name>
#   其他                    → /brain/bin/<name>
#
_update_global_bin_symlinks() {
    log "Updating /brain/bin/ symlinks..."

    mkdir -p "$BRAIN_BIN" "$BRAIN_BIN_MCP" "$BRAIN_BIN_HOOKS"

    local count_root=0 count_mcp=0 count_hooks=0

    for svc_dir in "$BRAIN_SERVICES"/*/; do
        [ -d "$svc_dir" ] || continue
        local svc_name
        svc_name=$(basename "$svc_dir")

        local bin_dir="$svc_dir/bin"
        [ -d "$bin_dir" ] || continue

        for exe in "$bin_dir"/*; do
            # 只处理可执行文件，跳过目录和 symlinks 到目录
            [ -f "$exe" ] && [ -x "$exe" ] || continue

            local exe_name
            exe_name=$(basename "$exe")

            # 分类
            local target_dir
            if [[ "$exe_name" == *_mcp_server ]] || [[ "$exe_name" == mcp-* ]]; then
                target_dir="$BRAIN_BIN_MCP"
            elif [[ "$exe_name" == *hook* ]] || [[ "$exe_name" == *_hook ]]; then
                target_dir="$BRAIN_BIN_HOOKS"
            else
                target_dir="$BRAIN_BIN"
            fi

            local symlink_path="$target_dir/$exe_name"
            local new_target
            new_target=$(realpath "$exe")

            # 已存在且正确则跳过
            if [ -L "$symlink_path" ]; then
                local existing_target
                existing_target=$(readlink -f "$symlink_path" 2>/dev/null || true)
                [ "$existing_target" = "$new_target" ] && continue
                rm -f "$symlink_path"
            elif [ -e "$symlink_path" ]; then
                continue  # 实体文件，不覆盖
            fi

            ln -sf "$new_target" "$symlink_path"

            case "$target_dir" in
                "$BRAIN_BIN_MCP")   count_mcp=$((count_mcp+1));;
                "$BRAIN_BIN_HOOKS") count_hooks=$((count_hooks+1));;
                *)                  count_root=$((count_root+1));;
            esac
        done
    done

    ok "symlinks updated: /brain/bin/ +$count_root  /brain/bin/mcp/ +$count_mcp  /brain/bin/hooks/ +$count_hooks"
}

# ─── build_lep_check ─────────────────────────────────────────────────
build_lep_check() {
    log "Building lep_check..."
    [ -f "$HOOKS_SRC/lep_check.c" ] || fail "lep_check.c not found: $HOOKS_SRC/lep_check.c"
    gcc -O2 -Wall -o "$HOOKS_SRC/lep_check" "$HOOKS_SRC/lep_check.c"
    ok "lep_check built → $HOOKS_SRC/lep_check"
}

# ─── build_mcp ───────────────────────────────────────────────────────
build_mcp() {
    log "Building brain_ipc_c MCP server..."
    [ -f "$MCP_SRC/Makefile" ] || fail "Makefile not found: $MCP_SRC/Makefile"
    make -C "$MCP_SRC" all
    [ -f "$MCP_SRC/bin/brain_ipc_c_mcp_server" ] || \
        fail "Build succeeded but binary not found at $MCP_SRC/bin/"
    ok "brain_ipc_c_mcp_server built → $MCP_SRC/bin/"
}

# ─── deploy_lep_check ────────────────────────────────────────────────
deploy_lep_check() {
    build_lep_check
    # lep_check 作为 hooks 的一部分，由 publish_base.sh --domain hooks 发布
    # 这里只确保编译产物存在于 source
    ok "lep_check ready at $HOOKS_SRC/lep_check (publish via: publish_base.sh --domain hooks)"
}

# ─── install_mcp_runtime ─────────────────────────────────────────────
install_mcp_runtime() {
    mkdir -p "$BRAIN_BIN" "$BRAIN_BIN_MCP"

    local binary="$MCP_SRC/bin/brain_ipc_c_mcp_server"
    [ -f "$binary" ] || fail "built MCP binary not found: $binary"

    local runtime_binary="$BRAIN_BIN/brain_ipc_c_mcp_server"
    local runtime_link="$BRAIN_BIN_MCP/mcp-brain_ipc_c"
    local stamp
    stamp="$(date +%Y%m%d_%H%M%S)"
    local backup_root="$PROJECT_ROOT/releases/publish_backups/$stamp/mcp_runtime"

    # 兼容现有运行时布局：真实二进制平铺在 /brain/bin 根，
    # agent 通过 /brain/bin/mcp/mcp-brain_ipc_c 这个稳定 symlink 发现入口。
    _backup_live_target "$runtime_binary" "$backup_root"
    _backup_live_target "$runtime_link" "$backup_root"

    cp -f "$binary" "$runtime_binary.new"
    chmod 755 "$runtime_binary.new"
    mv -f "$runtime_binary.new" "$runtime_binary"

    ln -sfn "$runtime_binary" "$runtime_link"

    _update_global_bin_symlinks

    ok "MCP runtime binary deployed: $runtime_binary"
    ok "MCP runtime entrypoint refreshed: $runtime_link -> $runtime_binary"
}

# ─── deploy_mcp ──────────────────────────────────────────────────────
deploy_mcp() {
    build_mcp
    install_mcp_runtime
}

# ─── verify ──────────────────────────────────────────────────────────
cmd_verify() {
    echo -e "${BOLD}══ /brain/bin/ symlink health ══${RESET}"
    local broken=0

    for dir in "$BRAIN_BIN" "$BRAIN_BIN_MCP" "$BRAIN_BIN_HOOKS"; do
        [ -d "$dir" ] || { warn "$dir: directory missing"; broken=$((broken+1)); continue; }
        echo -e "\n  ${CYAN}$dir/${RESET}"
        for link in "$dir"/*; do
            [ -L "$link" ] || continue
            local name
            name=$(basename "$link")
            if [ -e "$link" ]; then
                echo -e "    ${GREEN}✓${RESET} $name → $(readlink "$link")"
            else
                echo -e "    ${RED}✗${RESET} $name → $(readlink "$link") (BROKEN)"
                broken=$((broken+1))
            fi
        done
    done

    echo ""
    [ $broken -eq 0 ] && ok "All symlinks healthy" || warn "$broken broken symlink(s)"
}

# ─── Main ────────────────────────────────────────────────────────────
CMD="${1:-help}"
TARGET="${2:-all}"

case "$CMD" in
    build)
        case "$TARGET" in
            hooks|lep_check) build_lep_check ;;
            mcp)             build_mcp ;;
            all)             build_lep_check; build_mcp ;;
            *) fail "Unknown target: $TARGET" ;;
        esac
        ;;
    install)
        case "$TARGET" in
            mcp)             install_mcp_runtime ;;
            *) fail "Unknown target: $TARGET" ;;
        esac
        ;;
    deploy)
        case "$TARGET" in
            hooks|lep_check) deploy_lep_check ;;
            mcp)             deploy_mcp ;;
            all)             deploy_lep_check; deploy_mcp ;;
            *) fail "Unknown target: $TARGET" ;;
        esac
        ;;
    links)
        _update_global_bin_symlinks
        ;;
    verify)
        cmd_verify
        ;;
    help|*)
        echo "Usage: $0 <command> [target]"
        echo ""
        echo "Commands:"
        echo "  build  [hooks|mcp|all]   编译 C 二进制"
        echo "  install [mcp]            安装已编译的 MCP 运行时入口"
        echo "  deploy [hooks|mcp|all]   编译 + 部署"
        echo "  links                    刷新 /brain/bin/ 分类 symlinks"
        echo "  verify                   检查 /brain/bin/ symlink 健康状态"
        echo ""
        echo "Targets: hooks  mcp  all(default)"
        echo ""
        echo "注：Python hooks 内容发布请用 publish_base.sh --domain hooks"
        ;;
esac
