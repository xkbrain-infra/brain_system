#!/bin/bash
# Spec Build & Publish
#
# 用法:
#   ./build.sh validate          校验 src/spec/
#   ./build.sh diff              对比 src/spec/ vs base/spec/
#   ./build.sh test              运行测试套件
#   ./build.sh publish [VERSION] 校验 → 创建全域快照 → 发布到 base/spec/
#   ./build.sh publish --dry-run 仅校验 + 预览，不实际发布
#   ./build.sh versions          列出所有已发布版本
#   ./build.sh rollback VERSION  回滚 spec 到指定版本

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# build/scripts/spec/ → build/scripts/ → build/ → agent_abilities/
SERVICE_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SRC_SPEC_DIR="$SERVICE_DIR/src/spec"
TARGET_DIR="/brain/base/spec"
RELEASES_DIR="$SERVICE_DIR/releases"
VERSION_FILE="$SERVICE_DIR/build/version.yaml"
VALIDATE="$SCRIPT_DIR/validate.py"
TEST_DIR="$SERVICE_DIR/build/tests/spec"

RED='\033[31m'
GREEN='\033[32m'
YELLOW='\033[33m'
CYAN='\033[36m'
BOLD='\033[1m'
RESET='\033[0m'

log()  { echo -e "${CYAN}[spec]${RESET} $1"; }
ok()   { echo -e "${GREEN}[spec]${RESET} $1"; }
warn() { echo -e "${YELLOW}[spec]${RESET} $1"; }
fail() { echo -e "${RED}[spec]${RESET} $1"; exit 1; }

# ─── 读取当前版本号 ───
get_current_version() {
    grep '^version:' "$VERSION_FILE" 2>/dev/null | sed 's/version: *"\?\([^"]*\)"\?/\1/'
}

# ─── validate: 校验 src/spec/ ───
cmd_validate() {
    log "Validating source: $SRC_SPEC_DIR"
    python3 "$VALIDATE" "$SRC_SPEC_DIR"
}

# ─── diff: 对比 src/spec/ vs base/spec/ ───
cmd_diff() {
    log "Comparing src/spec/ vs base/spec/"
    diff -rq "$SRC_SPEC_DIR" "$TARGET_DIR" \
        --exclude='__pycache__' --exclude='*.bak' 2>/dev/null || true
}

# ─── test: 运行测试 ───
cmd_test() {
    log "Running spec tests..."
    local exit_code=0

    for test_file in test_index_chain.py test_role_coverage.py test_spec_coverage.py; do
        if [ -f "$TEST_DIR/$test_file" ]; then
            log "Running $test_file"
            python3 "$TEST_DIR/$test_file" "$SRC_SPEC_DIR" || exit_code=1
        fi
    done

    if [ $exit_code -eq 0 ]; then
        ok "All tests passed"
    else
        fail "Some tests failed"
    fi
    return $exit_code
}

# ─── versions: 列出已发布版本 ───
cmd_versions() {
    log "Published versions:"
    if [ ! -d "$RELEASES_DIR" ] || [ -z "$(ls -A "$RELEASES_DIR" 2>/dev/null)" ]; then
        warn "No releases yet."
        return 0
    fi
    for d in "$RELEASES_DIR"/v*/; do
        [ -d "$d" ] || continue
        local ver
        ver=$(basename "$d")
        local ts=""
        if [ -f "$d/RELEASE.yaml" ]; then
            ts=$(grep '^date:' "$d/RELEASE.yaml" | head -1 | sed 's/date: *"\?\([^"]*\)"\?/\1/')
        fi
        local domains=""
        if [ -f "$d/RELEASE.yaml" ]; then
            for dom in spec workflow knowledge evolution skill index; do
                grep -q "^  $dom: true" "$d/RELEASE.yaml" 2>/dev/null && domains="${domains}${dom} "
            done
        fi
        local commit=""
        commit=$(grep '^git_commit:' "$d/RELEASE.yaml" 2>/dev/null | sed 's/git_commit: *"\?\([^"]*\)"\?/\1/' || true)
        echo "  $ver  ($ts)  [${domains:-?}]${commit:+  @$commit}"
    done
    echo ""
    echo "  current: v$(get_current_version)"
}

# ─── publish: 校验 → 快照全域 → 发布 spec ───
cmd_publish() {
    local version="${1:-}"
    local dry_run=false

    if [ "$version" = "--dry-run" ]; then
        dry_run=true
        version=""
    fi

    if [ -z "$version" ]; then
        version=$(get_current_version)
        [ -n "$version" ] || fail "Cannot determine version. Set in $VERSION_FILE"
    fi

    local release_dir="$RELEASES_DIR/v$version"

    echo -e "${BOLD}══════ Spec Publish v$version ══════${RESET}"

    # Step 1: Validate
    log "Step 1/5: Validate source"
    python3 "$VALIDATE" "$SRC_SPEC_DIR" || fail "Source validation failed."

    # Step 2: Test
    log "Step 2/5: Run tests"
    if ls "$TEST_DIR"/test_*.py >/dev/null 2>&1; then
        cmd_test || fail "Tests failed. Fix before publishing."
    else
        warn "No tests found, skipping."
    fi

    # Step 3: Diff
    log "Step 3/5: Diff check"
    local changes
    changes=$(diff -rq "$SRC_SPEC_DIR" "$TARGET_DIR" \
        --exclude='__pycache__' --exclude='*.bak' 2>/dev/null || true)
    if [ -z "$changes" ]; then
        ok "No changes detected. base/spec/ is up to date."
        return 0
    fi
    echo "$changes" | head -20
    local change_count
    change_count=$(echo "$changes" | wc -l)
    log "$change_count file(s) changed"

    if [ "$dry_run" = true ]; then
        warn "Dry run. No changes applied."
        return 0
    fi

    # Step 4: 写 RELEASE.yaml + 更新 current symlink
    log "Step 4/5: Create release record → releases/v$version/"
    mkdir -p "$release_dir"

    local git_commit=""
    git_commit=$(git -C "$SERVICE_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")

    cat > "$release_dir/RELEASE.yaml" <<EOF
version: "$version"
date: "$(date -u +%Y-%m-%d)"
timestamp: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
spec_files_changed: $change_count
published_by: spec-build
git_commit: "$git_commit"
domains:
  spec: true
  workflow: true
  knowledge: true
  evolution: true
  skill: true
  index: true
EOF

    # 更新 current symlink
    ln -sfn "v$version" "$RELEASES_DIR/current"
    ok "releases/current → v$version"

    # Step 5: Sync spec → base/spec
    log "Step 5/5: Publish → base/spec/"
    rm -rf "$TARGET_DIR"
    cp -a "$SRC_SPEC_DIR" "$TARGET_DIR"
    find "$TARGET_DIR" -name '__pycache__' -type d | xargs rm -rf 2>/dev/null || true

    # Update version file timestamp
    sed -i "s/^last_build:.*/last_build: \"$(date -u +%Y-%m-%d)\"/" "$VERSION_FILE" 2>/dev/null || true

    # Final validation
    python3 "$VALIDATE" "$TARGET_DIR" > /dev/null 2>&1 \
        && ok "Published v$version → base/spec/ (${change_count} spec files changed)" \
        || fail "Post-publish validation failed! Run: git checkout -- base/spec/"
}

# ─── rollback: 回滚 spec 到指定版本（通过 git）───
cmd_rollback() {
    local version="${1:-}"
    [ -n "$version" ] || fail "Usage: $0 rollback VERSION (e.g. 2.0.0)"
    local release_dir="$RELEASES_DIR/v$version"
    [ -f "$release_dir/RELEASE.yaml" ] || fail "Release v$version not found: $release_dir/RELEASE.yaml"

    local git_commit
    git_commit=$(grep '^git_commit:' "$release_dir/RELEASE.yaml" | sed 's/git_commit: *"\?\([^"]*\)"\?/\1/')

    if [ -z "$git_commit" ] || [ "$git_commit" = "unknown" ]; then
        fail "No git_commit in RELEASE.yaml for v$version. Rollback manually via git."
    fi

    log "Rolling back spec to v$version (commit: $git_commit)..."
    git -C "$SERVICE_DIR" checkout "$git_commit" -- src/spec/
    ok "src/spec/ restored to v$version. Run 'publish' to apply to base/spec/."
}

# ─── Main ───
case "${1:-help}" in
    validate)   cmd_validate ;;
    diff)       cmd_diff ;;
    test)       cmd_test ;;
    publish)    cmd_publish "${2:-}" ;;
    versions)   cmd_versions ;;
    rollback)   cmd_rollback "${2:-}" ;;
    help|*)
        echo "Usage: $0 <command>"
        echo "  validate          Validate src/spec/"
        echo "  diff              Compare src/spec/ vs base/spec/"
        echo "  test              Run test suite"
        echo "  publish [VER]     Validate → full-domain snapshot → publish to base/spec/"
        echo "  publish --dry-run Preview without applying"
        echo "  versions          List published versions (with domain coverage)"
        echo "  rollback VERSION  Restore src/spec/ and base/spec/ from snapshot"
        ;;
esac
