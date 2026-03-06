#!/bin/bash
# Agent Abilities — 统一构建入口
# 规范: G-SPEC-STANDARD-AGENT-ABILITIES-BUILD
# 路径: /brain/base/spec/standards/infra/agent_abilities_build.yaml
#
# 流水线: diff → merge → build → deploy
#
# 用法:
#   ./build.sh diff   [target]   对比 /brain/base/ 与 src/ 的差异
#   ./build.sh merge  [target]   将 base 的变更合并回 src/（base → src）
#   ./build.sh build  [target]   src/ → bin/{module}/{version}/
#   ./build.sh deploy [target]   bin/{module}/current/ → releases/ → /brain/base/
#   ./build.sh publish [target]  完整流水线: diff → merge → confirm → build → deploy
#   ./build.sh versions          列出已发布版本
#   ./build.sh rollback VERSION  从 releases/{version}/ 回滚 /brain/base/
#
# Targets:
#   spec        规范文档
#   workflow    工作流程
#   knowledge   知识库
#   evolution   演进文档
#   skill       系统能力
#   index       base/index.yaml
#   hooks       Agent Hooks 运行时（走 build/scripts/hooks/build.sh）
#   mcp         brain_ipc_c MCP server（C 编译）
#   docs        spec + workflow + knowledge + evolution + skill + index
#   all         docs + hooks + mcp

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_DIR="$(dirname "$SCRIPT_DIR")"
SRC_DIR="$SERVICE_DIR/src"
SRC_BASE_DIR="$SRC_DIR/base"
BIN_DIR="$SERVICE_DIR/bin"
RELEASES_DIR="$SERVICE_DIR/releases"
VERSION_FILE="$SCRIPT_DIR/version.yaml"

RED='\033[31m'; GREEN='\033[32m'; YELLOW='\033[33m'
CYAN='\033[36m'; BOLD='\033[1m'; RESET='\033[0m'

log()  { echo -e "${CYAN}[build]${RESET} $1"; }
ok()   { echo -e "${GREEN}[build] ✓${RESET} $1"; }
warn() { echo -e "${YELLOW}[build] ⚠${RESET} $1"; }
fail() { echo -e "${RED}[build] ✗${RESET} $1"; exit 1; }
step() { echo -e "\n${BOLD}── $1 ──${RESET}"; }

# releases/current 必须是 symlink，不能是物理目录
# Linux 陷阱：ln -sfn 在目标是物理目录时会在目录内创建 symlink 而非替换
# 规范：G-SPEC-STANDARD-AGENT-ABILITIES-BUILD releases.current
_update_releases_current() {
    local version="$1"
    if [ -d "$RELEASES_DIR/current" ] && [ ! -L "$RELEASES_DIR/current" ]; then
        warn "releases/current 是物理目录（非 symlink），先删除再重建"
        rm -rf "$RELEASES_DIR/current"
    fi
    ln -sfn "v$version" "$RELEASES_DIR/current"
}

# ─── 全局 bin 目录 symlink 更新 ─────────────────────────────────────
_update_global_bin_symlinks() {
    local services_dir="/brain/infrastructure/service"
    local brain_bin="/brain/bin"

    # 确保 /brain/bin 存在
    [ -d "$brain_bin" ] || mkdir -p "$brain_bin"

    # 扫描所有服务
    local count=0
    for svc_dir in "$services_dir"/*/; do
        [ -d "$svc_dir" ] || continue
        local svc_name
        svc_name=$(basename "$svc_dir")

        # 跳过非服务目录
        case "$svc_name" in
            hooks|utils) continue ;;
        esac

        local bin_dir="$svc_dir/bin"
        [ -d "$bin_dir" ] || continue

        # 扫描 bin 目录下的可执行文件
        for exe in "$bin_dir"/*; do
            [ -f "$exe" ] || continue
            [ -x "$exe" ] || continue

            local exe_name
            exe_name=$(basename "$exe")

            # 跳过目录（current 等）
            [ -d "$exe" ] && continue

            local symlink_path="$brain_bin/$exe_name"
            local target_path="../infrastructure/service/$svc_name/bin/$exe_name"

            # 如果 symlink 已存在且指向不同目标，先删除
            if [ -L "$symlink_path" ]; then
                local existing_target
                existing_target=$(readlink -f "$symlink_path" 2>/dev/null || true)
                local new_target
                new_target=$(realpath "$exe" 2>/dev/null || true)
                if [ "$existing_target" != "$new_target" ]; then
                    rm -f "$symlink_path"
                else
                    continue  # 已存在且正确
                fi
            elif [ -e "$symlink_path" ]; then
                # 实体文件存在，跳过
                continue
            fi

            # 创建 symlink
            ln -sf "$target_path" "$symlink_path"
            ok "symlink: $exe_name -> $svc_name/bin/$exe_name"
            count=$((count + 1))
        done
    done

    # 确保 PATH 配置存在
    if [ ! -f /etc/profile.d/brain.sh ]; then
        echo 'export PATH="$PATH:/brain/bin"' > /etc/profile.d/brain.sh
        ok "created /etc/profile.d/brain.sh"
    fi

    ok "global bin symlinks: $count links updated"
}

# ─── 版本管理 ─────────────────────────────────────────────────────────
get_version() {
    grep '^version:' "$VERSION_FILE" 2>/dev/null \
        | sed 's/version: *"\?\([^"]*\)"\?/\1/' | tr -d '"'
}

# ─── Target 展开 ──────────────────────────────────────────────────────
# docs-targets: 直接 copy 类，有对应的 base/ 域
DOC_TARGETS="spec workflow knowledge evolution skill index"
# root-targets: 部署到 /brain/ 根目录的配置文件
ROOT_FILES="INIT.md CLAUDE.md AGENTS.md GEMINI.md"

expand_target() {
    case "$1" in
        docs) echo "$DOC_TARGETS" ;;
        all)  echo "$DOC_TARGETS hooks mcp root" ;;
        *)    echo "$1" ;;
    esac
}

# target → src 路径
src_of() {
    case "$1" in
        index) echo "$SRC_BASE_DIR/index.yaml" ;;
        hooks) echo "$SRC_BASE_DIR/hooks" ;;
        mcp)   echo "$SRC_DIR/mcp" ;;
        root)  echo "$SRC_BASE_DIR" ;;
        *)     echo "$SRC_BASE_DIR/$1" ;;
    esac
}

# target → base 路径
base_of() {
    case "$1" in
        index) echo "/brain/base/index.yaml" ;;
        root)  echo "/brain" ;;
        *)     echo "/brain/base/$1" ;;
    esac
}

# target → bin 路径（模块级，不含版本）
bin_module_of() { echo "$BIN_DIR/$1"; }

# ─── diff: base ↔ src ──────────────────────────────────────────────
cmd_diff() {
    local target="$1"
    local src base

    case "$target" in
        hooks|mcp|root)
            warn "$target: not in /brain/base/, skipping diff"
            return 0
            ;;
    esac

    src="$(src_of "$target")"
    base="$(base_of "$target")"

    if [ ! -e "$src" ]; then  warn "$target: src not found: $src"; return 1; fi
    if [ ! -e "$base" ]; then warn "$target: base not found: $base (not yet deployed)"; return 0; fi

    local changes
    changes=$(diff -rq "$base" "$src" \
        --exclude='__pycache__' --exclude='*.bak' --exclude='*.pyc' 2>/dev/null || true)

    if [ -z "$changes" ]; then
        ok "$target: in sync"
    else
        echo -e "${YELLOW}$target: differences (base ↔ src)${RESET}"
        echo "$changes" | sed 's/^/  /'
        echo ""
    fi
}

# ─── merge: base → src（git 三方合并）──────────────────────────────
# 方向: /brain/base/{domain}/ → src/{module}/
# 场景: base 被 agent 或其他工具直接修改，需要同步回 src
# 策略: 用 releases/current/{target}/ 作为 common ancestor
#   git merge-file src ancestor base → 干净合并或冲突标记
cmd_merge() {
    local target="$1"
    local src base

    case "$target" in
        hooks|mcp) warn "$target: not in /brain/base/, skip merge"; return 0 ;;
    esac

    src="$(src_of "$target")"
    base="$(base_of "$target")"

    if [ ! -e "$base" ]; then warn "$target: base not found, nothing to merge"; return 0; fi

    # ancestor = releases/current/{target}/
    local ancestor_link="$RELEASES_DIR/current"
    if [ ! -e "$ancestor_link" ]; then
        warn "$target: no previous release (releases/current missing), skipping merge"
        warn "$target: src is authoritative for first deploy"
        return 0
    fi
    local ancestor_real
    ancestor_real="$(realpath "$ancestor_link")"
    case "$target" in
        index) local ancestor="$ancestor_real/index.yaml" ;;
        *)     local ancestor="$ancestor_real/$target" ;;
    esac

    if [ ! -e "$ancestor" ]; then
        warn "$target: ancestor not in release ($ancestor), skipping merge"
        return 0
    fi

    # 单文件
    if [ -f "$src" ]; then
        _merge_file_git "$target" "$src" "$ancestor" "$base"
        return $?
    fi

    # 目录：逐文件 git merge-file
    local merged=0 skipped=0 conflicts=0 added=0

    # 收集 base + src 的文件并集
    local all_files
    all_files=$( (cd "$base" && find . -type f 2>/dev/null; \
                  cd "$src"  && find . -type f 2>/dev/null) \
        | grep -v '__pycache__\|\.bak$\|\.pyc$' | sort -u )

    while IFS= read -r rel; do
        [ -z "$rel" ] && continue
        local f_src="$src/$rel" f_base="$base/$rel" f_anc="$ancestor/$rel"

        # 只在 base 新增（agent 在线上新建文件）→ 复制到 src
        if [ -f "$f_base" ] && [ ! -f "$f_src" ]; then
            mkdir -p "$(dirname "$f_src")"
            cp -f "$f_base" "$f_src"
            added=$((added + 1))
            continue
        fi

        # 只在 src 新增 → 保留
        if [ -f "$f_src" ] && [ ! -f "$f_base" ]; then
            skipped=$((skipped + 1))
            continue
        fi

        # 两边都存在：三方合并
        if [ -f "$f_src" ] && [ -f "$f_base" ]; then
            # 先判断是否有差异
            if diff -q "$f_base" "$f_src" >/dev/null 2>&1; then
                continue  # 完全相同，跳过
            fi

            if [ ! -f "$f_anc" ]; then
                # 无 ancestor：两边都新增且内容不同
                warn "CONFLICT (no ancestor): $rel — keeping src, base version saved as ${rel}.base"
                cp -f "$f_base" "${f_src}.base"
                conflicts=$((conflicts + 1))
                continue
            fi

            # git merge-file: 把 base 的变更合并到 src，以 ancestor 为基准
            # 用临时副本，避免破坏原文件（失败时）
            local tmp_src
            tmp_src=$(mktemp)
            cp -f "$f_src" "$tmp_src"

            if git merge-file "$tmp_src" "$f_anc" "$f_base" 2>/dev/null; then
                # 干净合并
                cp -f "$tmp_src" "$f_src"
                merged=$((merged + 1))
            else
                # 有冲突：写入带冲突标记的结果
                cp -f "$tmp_src" "$f_src"
                warn "CONFLICT: $rel — conflict markers written, needs manual resolution"
                conflicts=$((conflicts + 1))
            fi
            rm -f "$tmp_src"
        fi
    done <<< "$all_files"

    echo ""
    ok "$target: merge complete — $merged merged, $added added, $skipped kept, $conflicts conflicts"
    if [ $conflicts -gt 0 ]; then
        warn "$target: $conflicts conflicts need manual resolution (look for <<<<<<< markers)"
        _notify_telegram "[BUILD] ⚠️ Merge 冲突\n\n域: $target\n冲突文件数: $conflicts\n\n请执行: build.sh resolve $target\n\n策略:\n  --accept-src  保留 src\n  --accept-base 保留 base\n  手动编辑删除 <<<<<<< 标记"
    fi
    return 0
}

# 单文件 git 三方合并
_merge_file_git() {
    local label="$1" src="$2" ancestor="$3" base="$4"

    if [ ! -f "$ancestor" ]; then
        warn "$label: no ancestor, skipping merge"
        return 0
    fi

    # 没有差异
    if diff -q "$base" "$src" >/dev/null 2>&1; then
        ok "$label: already in sync"
        return 0
    fi

    local tmp_src
    tmp_src=$(mktemp)
    cp -f "$src" "$tmp_src"

    if git merge-file "$tmp_src" "$ancestor" "$base" 2>/dev/null; then
        cp -f "$tmp_src" "$src"
        ok "$label: merged cleanly (base → src)"
    else
        cp -f "$tmp_src" "$src"
        warn "$label: CONFLICT — conflict markers written"
    fi
    rm -f "$tmp_src"
    return 0
}

# ─── conflict: 冲突检测与解决 ─────────────────────────────────────
CONFLICT_MARKER="<<<<<<<"
IPC_SOCKET="/tmp/brain_ipc.sock"

# 通过 IPC 发送 Telegram 通知
_notify_telegram() {
    local message="$1"
    local priority="${2:-high}"
    python3 -c "
import socket, json, sys, uuid
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
try:
    sock.connect('$IPC_SOCKET')
    msg = json.dumps({
        'action': 'send',
        'from': 'service-build',
        'to': 'service-telegram_api',
        'message_type': 'request',
        'priority': '$priority',
        'payload': {'content': sys.argv[1]}
    })
    sock.sendall((msg + '\\n').encode())
    resp = sock.recv(4096).decode()
    sock.close()
except Exception as e:
    print(f'[build] warn: telegram notify failed: {e}', file=sys.stderr)
" "$message" 2>/dev/null || warn "telegram notification failed (non-fatal)"
}

# 检查 src 目录是否有未解决的冲突标记
# 返回: 0=无冲突, 1=有冲突
_check_conflicts() {
    local target="$1"
    local src
    src="$(src_of "$target")"

    [ -e "$src" ] || return 0

    local conflict_files
    if [ -f "$src" ]; then
        grep -l "^$CONFLICT_MARKER" "$src" 2>/dev/null && return 1
        return 0
    fi

    conflict_files=$(grep -rl "^$CONFLICT_MARKER" "$src" \
        --include='*.yaml' --include='*.yml' --include='*.md' \
        --include='*.json' --include='*.py' --include='*.sh' \
        --include='*.toml' --include='*.txt' 2>/dev/null || true)

    if [ -n "$conflict_files" ]; then
        echo -e "${RED}Unresolved conflicts in $target:${RESET}"
        echo "$conflict_files" | sed "s|^$src/|  |"
        _notify_telegram "[BUILD] 🚫 构建被阻止\n\n域: $target\n原因: 存在未解决的 merge 冲突\n\n冲突文件:\n$(echo "$conflict_files" | sed "s|^$src/||" | head -10)\n\n请执行: build.sh resolve $target"
        return 1
    fi
    return 0
}

# 列出 + 解决冲突
# 用法: build.sh resolve [target] [--accept-src|--accept-base]
cmd_resolve() {
    local target="$1"
    local strategy="${2:-}"
    local src
    src="$(src_of "$target")"

    [ -e "$src" ] || { ok "$target: no src, nothing to resolve"; return 0; }

    local conflict_files
    if [ -f "$src" ]; then
        conflict_files=$(grep -l "^$CONFLICT_MARKER" "$src" 2>/dev/null || true)
    else
        conflict_files=$(grep -rl "^$CONFLICT_MARKER" "$src" \
            --include='*.yaml' --include='*.yml' --include='*.md' \
            --include='*.json' --include='*.py' --include='*.sh' \
            --include='*.toml' --include='*.txt' 2>/dev/null || true)
    fi

    if [ -z "$conflict_files" ]; then
        ok "$target: no conflicts found"
        return 0
    fi

    local count
    count=$(echo "$conflict_files" | wc -l)
    echo -e "${YELLOW}$target: $count file(s) with conflicts:${RESET}"
    echo "$conflict_files" | sed "s|^$src/|  |"
    echo ""

    case "$strategy" in
        --accept-src)
            # 保留 src 侧（删除冲突标记，取 <<<<<<< 到 ======= 之间的内容）
            while IFS= read -r f; do
                [ -z "$f" ] && continue
                sed -i '/^<<<<<<</d; /^=======/,/^>>>>>>>/d' "$f"
                ok "resolved (accept-src): $(echo "$f" | sed "s|^$src/||")"
            done <<< "$conflict_files"
            ok "$target: all conflicts resolved with --accept-src"
            _notify_telegram "[BUILD] ✅ 冲突已解决 ($target)\n策略: accept-src\n可以继续 build" "normal"
            ;;
        --accept-base)
            # 保留 base 侧（删除冲突标记，取 ======= 到 >>>>>>> 之间的内容）
            while IFS= read -r f; do
                [ -z "$f" ] && continue
                sed -i '/^<<<<<<</,/^=======/d; /^>>>>>>>/d' "$f"
                ok "resolved (accept-base): $(echo "$f" | sed "s|^$src/||")"
            done <<< "$conflict_files"
            ok "$target: all conflicts resolved with --accept-base"
            _notify_telegram "[BUILD] ✅ 冲突已解决 ($target)\n策略: accept-base\n可以继续 build" "normal"
            ;;
        "")
            # 无策略：只列出，不解决
            echo "To resolve:"
            echo "  $0 resolve $target --accept-src    # keep src version"
            echo "  $0 resolve $target --accept-base   # keep base version"
            echo "  Or manually edit files to remove <<<<<<< markers"
            ;;
        *)
            fail "Unknown strategy: $strategy (use --accept-src or --accept-base)"
            ;;
    esac
}

# ─── test: 运行 build/tests/{target}/ 下的测试 ──────────────────────
_run_tests() {
    local target="$1"
    local test_dir="$SRC_DIR/tests/base/$target"
    # hooks 测试在 src/tests/hooks/
    [ "$target" = "hooks" ] && test_dir="$SRC_DIR/tests/hooks"
    [ -d "$test_dir" ] || return 0  # 无测试目录则跳过

    local test_files
    test_files=$(find "$test_dir" -maxdepth 1 -name 'test_*.py' 2>/dev/null)
    [ -n "$test_files" ] || return 0

    log "$target: running tests in build/tests/$target/"
    local failed=0
    for f in $test_files; do
        python3 "$f" "$(src_of "$target")" 2>&1 | sed 's/^/  /' || failed=1
    done
    [ $failed -eq 0 ] || fail "$target: tests failed, aborting build"
    ok "$target: all tests passed"
}

# ─── build: src → bin/{module}/{version}/ ────────────────────────────
cmd_build() {
    local target="$1"

    # 冲突门禁：有未解决冲突则禁止 build
    if ! _check_conflicts "$target"; then
        fail "$target: unresolved merge conflicts — run '$0 resolve $target' first"
    fi

    local version
    version="$(get_version)"
    local bin_mod
    bin_mod="$(bin_module_of "$target")"
    local bin_ver="$bin_mod/v$version"

    case "$target" in
        spec|workflow|knowledge|evolution|skill)
            local src="$(src_of "$target")"
            [ -d "$src" ] || fail "$target: src not found: $src"
            rm -f "$bin_mod/current"
            _run_tests "$target"
            log "$target: building v$version → bin/$target/v$version/"
            rm -rf "$bin_ver"
            mkdir -p "$bin_ver"
            cp -a "$src/." "$bin_ver/"
            find "$bin_ver" -name '__pycache__' -type d | xargs rm -rf 2>/dev/null || true
            ;;
        index)
            local src="$(src_of "index")"
            [ -f "$src" ] || fail "index: src not found: $src"
            rm -f "$bin_mod/current"
            log "index: building v$version"
            mkdir -p "$bin_mod"
            cp -f "$src" "$bin_mod/index-v$version.yaml"
            ln -sfn "index-v$version.yaml" "$bin_mod/current"
            ok "index: built v$version → bin/index/current"
            return 0
            ;;
        hooks)
            log "hooks: delegating to build/scripts/hooks/build.sh"
            bash "$SCRIPT_DIR/scripts/hooks/build.sh"
            return 0
            ;;
        mcp)
            log "mcp: delegating to build/scripts/mcp/build.sh"
            bash "$SCRIPT_DIR/scripts/mcp/build.sh" all
            return 0
            ;;
        root)
            local src="$(src_of "root")"
            mkdir -p "$bin_ver"
            for f in $ROOT_FILES; do
                [ -f "$src/$f" ] || { warn "root: $f not found in src, skipping"; continue; }
                cp -f "$src/$f" "$bin_ver/$f"
            done
            ln -sfn "v$version" "$bin_mod/current"
            ok "root: built v$version → bin/root/current"
            return 0
            ;;
        *) fail "Unknown target: $target" ;;
    esac

    # 更新 current symlink
    ln -sfn "v$version" "$bin_mod/current"
    ok "$target: built v$version → bin/$target/current"
}

# ─── deploy: build + bin/{module}/current → releases/{version}/ → /brain/base/ ──
# ─── skill 分发：SKILL.md → .claude/skills/ ──────────────────────────
_deploy_skills() {
    local skill_base="$1"   # /brain/base/skill/
    local REGISTRY="/brain/infrastructure/config/agentctl/agents_registry.yaml"

    # 扫描所有含 SKILL.md 的子目录
    local skill_dirs
    skill_dirs=$(find "$skill_base" -maxdepth 2 -name "SKILL.md" -printf '%h
' 2>/dev/null | sort -u)

    if [ -z "$skill_dirs" ]; then
        log "skill: no SKILL.md found in $skill_base, skip distribution"
        return 0
    fi

    local skill_count=0
    local skill_names=""

    # 1. Deploy to global /brain/.claude/skills/
    while IFS= read -r skill_dir; do
        [ -z "$skill_dir" ] && continue
        local skill_name
        skill_name=$(basename "$skill_dir")
        local target_dir="/brain/.claude/skills/$skill_name"
        mkdir -p "$target_dir"
        cp -f "$skill_dir/SKILL.md" "$target_dir/SKILL.md"
        skill_count=$((skill_count + 1))
        skill_names="$skill_names $skill_name"
    done <<< "$skill_dirs"
    ok "skill: deployed $skill_count skills → /brain/.claude/skills/ ($skill_names)"

    # 2. Deploy to all agents in agentctl registry
    local agent_paths
    agent_paths=$(python3 -c "
import yaml, sys
with open('$REGISTRY') as f:
    data = yaml.safe_load(f)
for agents in data.get('groups', {}).values():
    for a in agents:
        p = a.get('path', '').strip()
        at = a.get('agent_type', 'claude').strip()
        if p and at == 'claude':
            print(p)
" 2>/dev/null)

    local agent_count=0
    while IFS= read -r agent_path; do
        [ -z "$agent_path" ] && continue
        while IFS= read -r skill_dir; do
            [ -z "$skill_dir" ] && continue
            local skill_name
            skill_name=$(basename "$skill_dir")
            local target_dir="$agent_path/.claude/skills/$skill_name"
            mkdir -p "$target_dir"
            cp -f "$skill_dir/SKILL.md" "$target_dir/SKILL.md"
        done <<< "$skill_dirs"
        agent_count=$((agent_count + 1))
    done <<< "$agent_paths"

    ok "skill: distributed $skill_count skills to $agent_count agents"
}

cmd_deploy() {
    local target="$1"
    local version
    version="$(get_version)"

    # 强制先 build，确保部署的是最新产物
    log "$target: building before deploy..."
    cmd_build "$target"
    local release_ver="$RELEASES_DIR/v$version"

    case "$target" in
        hooks)
            local hooks_current="$BIN_DIR/hooks/current"
            [ -e "$hooks_current" ] || fail "hooks: bin/hooks/current not found — build failed or not yet run"

            local HOOKS=( pre_tool_use post_tool_use session_start session_end user_prompt_submit )
            local REGISTRY="/brain/infrastructure/config/agentctl/agents_registry.yaml"

            # 1. Deploy modules to /brain/base/hooks/ (handler import target)
            log "hooks: deploying modules → /brain/base/hooks/"
            local BASE_HOOKS="/brain/base/hooks"
            # 清空旧结构，完整替换
            rm -rf "$BASE_HOOKS"
            mkdir -p "$BASE_HOOKS"
            # 复制全部构建产物（模块 + entry 脚本）
            cp -r "$hooks_current"/* "$BASE_HOOKS/"
            find "$BASE_HOOKS" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
            ok "hooks: deployed modules → $BASE_HOOKS"

            # 2. Deploy entry scripts to global /brain/.claude/hooks/
            log "hooks: deploying entries → /brain/.claude/hooks/"
            mkdir -p "/brain/.claude/hooks"
            for hook in "${HOOKS[@]}"; do
                [ -f "$hooks_current/$hook" ] || continue
                cp -f "$hooks_current/$hook" "/brain/.claude/hooks/$hook"
                chmod +x "/brain/.claude/hooks/$hook"
            done
            ok "hooks: deployed ${#HOOKS[@]} entries → /brain/.claude/hooks/"

            # 3. Deploy entry scripts to all agents in agentctl registry
            log "hooks: deploying entries to all agentctl-managed agents..."
            local agent_count=0
            local agent_paths
            agent_paths=$(python3 -c "
import yaml, sys
with open('$REGISTRY') as f:
    data = yaml.safe_load(f)
for agents in data.get('groups', {}).values():
    for a in agents:
        p = a.get('path', '').strip()
        if p:
            print(p)
" 2>/dev/null)

            while IFS= read -r agent_path; do
                [ -z "$agent_path" ] && continue
                local hooks_dir="$agent_path/.claude/hooks"
                mkdir -p "$hooks_dir"
                # 先删除 dangling symlinks
                for hook in "${HOOKS[@]}"; do
                    [ -L "$hooks_dir/$hook" ] && ! [ -e "$hooks_dir/$hook" ] && rm -f "$hooks_dir/$hook"
                done
                for hook in "${HOOKS[@]}"; do
                    [ -f "$hooks_current/$hook" ] || continue
                    cp -f "$hooks_current/$hook" "$hooks_dir/$hook"
                    chmod +x "$hooks_dir/$hook"
                done
                agent_count=$((agent_count + 1))
            done <<< "$agent_paths"

            ok "hooks: deployed to $agent_count agents"

            # 3b. Deploy role-specific overrides
            local OVERRIDES_DIR="$hooks_current/overrides"
            if [ -d "$OVERRIDES_DIR" ]; then
                for override_dir in "$OVERRIDES_DIR"/*/; do
                    [ -d "$override_dir" ] || continue
                    local role_name
                    role_name=$(basename "$override_dir")
                    local agent_path
                    agent_path=$(python3 -c "
import yaml
with open('$REGISTRY') as f:
    data = yaml.safe_load(f)
for agents in data.get('groups', {}).values():
    for a in agents:
        if a.get('name','') == 'agent-${role_name}' or a.get('name','') == '${role_name}':
            print(a.get('path',''))
            break
" 2>/dev/null)
                    if [ -n "$agent_path" ]; then
                        for hook_file in "$override_dir"/*; do
                            [ -f "$hook_file" ] || continue
                            # 跳过 .py 模块（由框架动态加载，不是入口脚本）
                            [[ "$hook_file" == *.py ]] && continue
                            local hook_name
                            hook_name=$(basename "$hook_file")
                            rm -f "$agent_path/.claude/hooks/$hook_name"
                            cp "$hook_file" "$agent_path/.claude/hooks/$hook_name"
                            chmod +x "$agent_path/.claude/hooks/$hook_name"
                        done
                        log "hooks: override deployed for $role_name → $agent_path"
                    fi
                done
            fi

            # 4. Record to releases/
            mkdir -p "$release_ver/hooks"
            cp -r "$hooks_current"/* "$release_ver/hooks/"
            find "$release_ver/hooks" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
            _update_releases_current "$version"
            ok "hooks: recorded → releases/v$version/hooks/"

            # 更新全局 bin symlinks
            _update_global_bin_symlinks

            return 0
            ;;
        mcp)
            local mcp_bin="$BIN_DIR/mcp/brain_ipc_c_mcp_server"
            [ -f "$mcp_bin" ] || fail "mcp: binary not found: $mcp_bin — run build first"
            log "mcp: deploying to releases/current/mcp/ and /brain/bin/mcp/"
            mkdir -p "$release_ver/mcp"
            cp -f "$mcp_bin" "$release_ver/mcp/brain_ipc_c_mcp_server"
            _update_releases_current "$version"
            # 更新 /brain/bin/mcp/ symlink 指向
            ln -sf "$RELEASES_DIR/current/mcp/brain_ipc_c_mcp_server" \
                "/brain/bin/mcp/mcp-brain_ipc_c"
            ok "mcp: deployed → releases/v$version/mcp/ + /brain/bin/mcp/mcp-brain_ipc_c"
            return 0
            ;;
        root)
            local bin_mod
            bin_mod="$(bin_module_of "root")"
            local bin_current="$bin_mod/current"
            [ -e "$bin_current" ] || fail "root: bin/root/current not found — run build first"
            log "root: deploying to /brain/"
            mkdir -p "$release_ver/root"
            for f in $ROOT_FILES; do
                local src_f
                src_f="$(realpath "$bin_current")/$f"
                [ -f "$src_f" ] || { warn "root: $f not in bin, skipping"; continue; }
                cp -f "$src_f" "$release_ver/root/$f"
                cp -f "$src_f" "/brain/$f"
                ok "root: deployed $f → /brain/$f"
            done
            _update_releases_current "$version"
            _write_release_yaml "$release_ver" "$version"
            return 0
            ;;
    esac

    local bin_mod
    bin_mod="$(bin_module_of "$target")"
    local bin_current="$bin_mod/current"

    [ -e "$bin_current" ] || fail "$target: bin/$target/current not found — build failed or not yet run"

    local base="$(base_of "$target")"

    # 1. copy bin/current → releases/v{n}/{domain}/
    log "$target: copy bin/$target/current → releases/v$version/$target/"
    mkdir -p "$release_ver"

    case "$target" in
        index)
            cp -f "$(realpath "$bin_current")" "$release_ver/index.yaml"
            ;;
        *)
            rm -rf "$release_ver/$target"
            cp -a "$(realpath "$bin_current")/." "$release_ver/$target/"
            ;;
    esac

    # 2. copy releases/v{n}/{domain} → /brain/base/{domain}
    log "$target: copy releases/v$version/$target → $base"
    case "$target" in
        index)
            cp -f "$release_ver/index.yaml" "$base"
            ;;
        *)
            rm -rf "$base"
            cp -a "$release_ver/$target/." "$base/"
            ;;
    esac

    # 3. 更新 releases/current symlink 和 RELEASE.yaml
    _update_releases_current "$version"
    _write_release_yaml "$release_ver" "$version"

    # 4. skill 额外步骤：分发 SKILL.md 到 .claude/skills/
    if [ "$target" = "skill" ]; then
        _deploy_skills "$base"
    fi

    ok "$target: deployed v$version → $base"
}

_write_release_yaml() {
    local dir="$1" version="$2"
    local git_commit=""
    git_commit=$(git -C "$SERVICE_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")

    # 统计部署了哪些域
    local domains_spec="false"; [ -d "$dir/spec" ]      && domains_spec="true"
    local domains_wf="false";   [ -d "$dir/workflow" ]  && domains_wf="true"
    local domains_kn="false";   [ -d "$dir/knowledge" ] && domains_kn="true"
    local domains_ev="false";   [ -d "$dir/evolution" ] && domains_ev="true"
    local domains_sk="false";   [ -d "$dir/skill" ]     && domains_sk="true"
    local domains_ix="false";   [ -f "$dir/index.yaml" ] && domains_ix="true"

    cat > "$dir/RELEASE.yaml" <<EOF
version: "$version"
date: "$(date -u +%Y-%m-%d)"
timestamp: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
published_by: build.sh
git_commit: "$git_commit"
domains:
  spec:      $domains_spec
  workflow:  $domains_wf
  knowledge: $domains_kn
  evolution: $domains_ev
  skill:     $domains_sk
  index:     $domains_ix
EOF
}

# ─── publish: 完整流水线（diff → merge → confirm → build → deploy）──
cmd_publish() {
    local target="$1"
    local version
    version="$(get_version)"

    echo -e "${BOLD}══════ Publish: $target @ v$version ══════${RESET}"

    case "$target" in
        hooks|mcp|root)
            # 无 base/ 对应域，无需 diff/merge，直接 deploy（含 build）
            step "Deploy (build + deploy)"
            cmd_deploy "$target"
            return 0
            ;;
    esac

    # Step 1: diff
    step "Step 1/3: Diff (base ↔ src)"
    local src base changes
    src="$(src_of "$target")"
    base="$(base_of "$target")"

    if [ -e "$base" ]; then
        changes=$(diff -rq "$base" "$src" \
            --exclude='__pycache__' --exclude='*.bak' --exclude='*.pyc' 2>/dev/null || true)
        if [ -n "$changes" ]; then
            echo -e "${YELLOW}Differences detected:${RESET}"
            echo "$changes" | sed 's/^/  /'
        else
            ok "No differences, base and src are in sync"
            changes=""
        fi
    else
        warn "base not found ($base), skipping diff"
        changes=""
    fi

    # Step 2: merge（如果有差异）
    if [ -n "$changes" ]; then
        step "Step 2/3: Merge (base → src)"
        cmd_merge "$target" || fail "Merge cancelled or failed"
    else
        step "Step 2/3: Merge — skipped (no diff)"
    fi

    # 冲突门禁
    if ! _check_conflicts "$target"; then
        fail "$target: unresolved merge conflicts after merge — run '$0 resolve $target' first"
    fi

    # Step 3: deploy（内含 build）
    step "Step 3/3: Deploy (build → bin → releases → base)"
    cmd_deploy "$target"

    echo ""
    ok "publish $target @ v$version complete"
}

# ─── stats: 生成覆盖统计 → knowledge ────────────────────────────────
cmd_stats() {
    local output_dir="$SRC_BASE_DIR/knowledge/brian_system/spec"
    log "Generating spec/lep/hooks stats..."
    python3 "$SCRIPT_DIR/scripts/stats/generate_stats.py" \
        "$SRC_BASE_DIR" "$output_dir"
    ok "stats written → src/base/knowledge/brian_system/spec/{spec_stats.yaml, spec_stats.md}"
}

# ─── versions ────────────────────────────────────────────────────────
cmd_versions() {
    log "Published releases:"
    [ -d "$RELEASES_DIR" ] || { warn "No releases yet."; return 0; }
    for d in "$RELEASES_DIR"/v*/; do
        [ -d "$d" ] || continue
        local ver ts domains="" commit=""
        ver="$(basename "$d")"
        ts="$(grep '^date:' "$d/RELEASE.yaml" 2>/dev/null | sed "s/date: *['\"]*//" | tr -d "'\"" || true)"
        commit="$(grep '^git_commit:' "$d/RELEASE.yaml" 2>/dev/null | sed "s/git_commit: *['\"]*//" | tr -d "'\"" || true)"
        for dom in spec workflow knowledge evolution skill index; do
            grep -q "^  $dom:.*true" "$d/RELEASE.yaml" 2>/dev/null && domains="$domains$dom "
        done
        echo "  $ver  ($ts)  [$domains] ${commit:+@$commit}"
    done
    local cur
    cur="$(readlink "$RELEASES_DIR/current" 2>/dev/null || echo "(none)")"
    echo ""
    echo "  current: $cur  (version.yaml: v$( get_version ))"
}

# ─── rollback ────────────────────────────────────────────────────────
cmd_rollback() {
    local version="${1:-}"
    [ -n "$version" ] || fail "Usage: rollback VERSION"
    local release_dir="$RELEASES_DIR/v$version"
    [ -d "$release_dir" ] || fail "Release v$version not found"

    echo -e "${BOLD}══════ Rollback → v$version ══════${RESET}"

    for domain in spec workflow knowledge evolution skill; do
        [ -d "$release_dir/$domain" ] || continue
        log "Restoring $domain..."
        rm -rf "/brain/base/$domain"
        cp -a "$release_dir/$domain/." "/brain/base/$domain/"
        ok "$domain restored"
    done
    [ -f "$release_dir/index.yaml" ] && cp -f "$release_dir/index.yaml" /brain/base/index.yaml && ok "index restored"

    _update_releases_current "$version"
    ok "Rollback complete. releases/current → v$version"
}

# ─── Main ────────────────────────────────────────────────────────────
CMD="${1:-help}"
TARGET_RAW="${2:-docs}"

# AUTO_DEPLOY=1 跳过交互确认（CI 用）
AUTO_CONFIRM="${AUTO_CONFIRM:-0}"

case "$CMD" in
    diff)
        TARGETS="$(expand_target "$TARGET_RAW")"
        echo -e "${BOLD}══ Diff: base ↔ src [$TARGET_RAW] ══${RESET}"
        for t in $TARGETS; do cmd_diff "$t"; done
        ;;
    merge)
        TARGETS="$(expand_target "$TARGET_RAW")"
        echo -e "${BOLD}══ Merge: base → src [$TARGET_RAW] ══${RESET}"
        for t in $TARGETS; do cmd_merge "$t"; done
        ;;
    resolve)
        STRATEGY="${3:-}"
        TARGETS="$(expand_target "$TARGET_RAW")"
        echo -e "${BOLD}══ Resolve conflicts [$TARGET_RAW] ══${RESET}"
        for t in $TARGETS; do cmd_resolve "$t" "$STRATEGY"; done
        ;;
    conflicts)
        TARGETS="$(expand_target "$TARGET_RAW")"
        echo -e "${BOLD}══ Check conflicts [$TARGET_RAW] ══${RESET}"
        has_any=0
        for t in $TARGETS; do _check_conflicts "$t" || has_any=1; done
        [ $has_any -eq 0 ] && ok "No conflicts in $TARGET_RAW"
        ;;
    build)
        TARGETS="$(expand_target "$TARGET_RAW")"
        echo -e "${BOLD}══ Build: src → bin [$TARGET_RAW] ══${RESET}"
        for t in $TARGETS; do cmd_build "$t"; done
        ok "Build done: $TARGET_RAW"
        ;;
    deploy)
        TARGETS="$(expand_target "$TARGET_RAW")"
        echo -e "${BOLD}══ Deploy: bin → releases → base [$TARGET_RAW] ══${RESET}"
        for t in $TARGETS; do cmd_deploy "$t"; done
        ok "Deploy done: $TARGET_RAW"
        ;;
    publish)
        TARGETS="$(expand_target "$TARGET_RAW")"
        for t in $TARGETS; do cmd_publish "$t"; done
        ;;
    stats)
        cmd_stats
        ;;
    versions)
        cmd_versions
        ;;
    rollback)
        cmd_rollback "${2:-}"
        ;;
    help|*)
        echo "Usage: $0 <command> [target]"
        echo ""
        echo "Commands:"
        echo "  diff    [target]   Compare /brain/base/ ↔ src/"
        echo "  merge   [target]   Merge base changes → src/ (git 3-way merge)"
        echo "  resolve [target] [--accept-src|--accept-base]  Resolve merge conflicts"
        echo "  conflicts [target]  Check for unresolved conflict markers"
        echo "  build   [target]   src/ → bin/{module}/v{version}/"
        echo "  deploy  [target]   bin/{module}/current → releases/ → /brain/base/"
        echo "  publish [target]   Full pipeline: diff → merge → build → deploy"
        echo "  versions           List published releases"
        echo "  rollback VERSION   Restore /brain/base/ from releases/{version}/"
        echo ""
        echo "  stats              Generate spec/lep/hooks coverage stats → knowledge"
echo "Targets: spec workflow knowledge evolution skill index hooks mcp root"
        echo "         docs = spec+workflow+knowledge+evolution+skill+index"
        echo "         all  = docs+hooks+mcp+root"
        ;;
esac
