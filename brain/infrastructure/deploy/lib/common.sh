#!/bin/bash
# deploy/lib/common.sh — 共用函数库
# 被各 service deploy.sh 引用

# ─── 颜色 ───────────────────────────────────────────────────────────
RED='\033[31m'
GREEN='\033[32m'
YELLOW='\033[33m'
CYAN='\033[36m'
BOLD='\033[1m'
RESET='\033[0m'

# ─── 日志函数 ────────────────────────────────────────────────────────
log()  { echo -e "${CYAN}[deploy]${RESET} $1"; }
ok()   { echo -e "${GREEN}[deploy] ✓${RESET} $1"; }
warn() { echo -e "${YELLOW}[deploy] ⚠${RESET} $1"; }
fail() { echo -e "${RED}[deploy] ✗${RESET} $1"; exit 1; }
skip() { echo -e "${YELLOW}[deploy] -${RESET} $1 (skipped)"; }

# ─── 列出所有 Claude agents ─────────────────────────────────────────
# 查找 /brain/groups 下所有有 .claude 目录的 agents
# 返回格式：每行一个 .claude 目录路径
list_claude_agents() {
    find /brain/groups -maxdepth 5 -type d -name ".claude" 2>/dev/null \
        | grep "/agents/" \
        | sort
}

# ─── 文件部署函数 ────────────────────────────────────────────────────
# deploy_file SRC DST_DIR [MODE]
# 复制文件到目标目录，设置权限，带错误处理
deploy_file() {
    local src="$1"
    local dst_dir="$2"
    local mode="${3:-755}"

    if [ ! -f "$src" ]; then
        warn "deploy_file: src not found: $src"
        return 1
    fi
    if [ ! -d "$dst_dir" ]; then
        warn "deploy_file: dst_dir not found: $dst_dir"
        return 1
    fi

    local filename
    filename="$(basename "$src")"
    cp -f "$src" "$dst_dir/$filename"
    chmod "$mode" "$dst_dir/$filename"
    return 0
}

# ─── 汇总计数器 ──────────────────────────────────────────────────────
DEPLOY_OK=0
DEPLOY_SKIP=0
DEPLOY_FAIL=0

count_ok()   { DEPLOY_OK=$((DEPLOY_OK + 1)); }
count_skip() { DEPLOY_SKIP=$((DEPLOY_SKIP + 1)); }
count_fail() { DEPLOY_FAIL=$((DEPLOY_FAIL + 1)); }

print_summary() {
    local label="${1:-Deploy}"
    echo ""
    echo -e "${BOLD}── $label Summary ──${RESET}"
    echo -e "  ${GREEN}OK${RESET}:     $DEPLOY_OK"
    echo -e "  ${YELLOW}Skipped${RESET}: $DEPLOY_SKIP"
    echo -e "  ${RED}Failed${RESET}:  $DEPLOY_FAIL"
    echo ""
    if [ "$DEPLOY_FAIL" -gt 0 ]; then
        echo -e "${RED}Deploy completed with $DEPLOY_FAIL failure(s)${RESET}"
        return 1
    else
        echo -e "${GREEN}Deploy completed successfully${RESET}"
        return 0
    fi
}
