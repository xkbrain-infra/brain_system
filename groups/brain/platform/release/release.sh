#!/bin/bash
#
# Brain System Release Manager
# 用途: 统一管理 brain 系统的发布流程
# 用法: ./release.sh [command] [options]
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_DIR="$(dirname "$SCRIPT_DIR")"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 读取当前版本
source_version() {
    if [[ -f "$RELEASE_DIR/VERSION" ]]; then
        # shellcheck source=/dev/null
        source "$RELEASE_DIR/VERSION"
        echo "${VERSION:-2.1.0}"
    else
        echo "2.1.0"
    fi
}

# 显示帮助
show_help() {
    cat << EOF
Brain System Release Manager

Usage: $0 <command> [options]

Commands:
    build [version]         Build release image (default: current version)
    publish [version]       Publish image to registry
    version <new_version>   Update version number
    list                    List available releases
    clean                   Clean build artifacts
    help                    Show this help message

Examples:
    $0 build                # Build with current version
    $0 build 2.2.0          # Build specific version
    $0 publish              # Publish current version
    $0 version 2.2.0        # Update version to 2.2.0
    $0 list                 # List published releases

EOF
}

# 构建命令
cmd_build() {
    local version="${1:-$(source_version)}"
    log_info "Building release version: $version"
    "$SCRIPT_DIR/build.sh" "$version"
}

# 发布命令
cmd_publish() {
    local version="${1:-$(source_version)}"
    log_info "Publishing release version: $version"
    "$SCRIPT_DIR/publish.sh" "$version"
}

# 更新版本号
cmd_version() {
    local new_version="${1:-}"
    if [[ -z "$new_version" ]]; then
        log_error "Please specify a version number"
        exit 1
    fi

    local current_version
    current_version=$(source_version)

    log_info "Updating version: $current_version -> $new_version"

    # 更新 VERSION 文件
    sed -i "s/^VERSION=.*/VERSION=$new_version/" "$RELEASE_DIR/VERSION"

    log_success "Version updated to $new_version"
    log_info "Remember to commit the VERSION file"
}

# 列出发布历史
cmd_list() {
    log_info "Available releases:"

    # 本地镜像
    echo ""
    echo "Local Docker images:"
    docker images --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}" | grep "brain/system" || echo "  No local images found"

    # 构建的包
    echo ""
    echo "Release packages:"
    if [[ -d "$RELEASE_DIR/packages" ]]; then
        ls -lh "$RELEASE_DIR/packages"/*.tar.gz 2>/dev/null | awk '{print "  " $9 " (" $5 ")"}' || echo "  No packages found"
    else
        echo "  No packages directory"
    fi

    # 发布历史
    echo ""
    echo "Publish history:"
    if [[ -f "$RELEASE_DIR/.publish_history" ]]; then
        tail -10 "$RELEASE_DIR/.publish_history" | sed 's/^/  /'
    else
        echo "  No publish history"
    fi
}

# 清理命令
cmd_clean() {
    log_info "Cleaning build artifacts..."

    # 删除构建目录
    rm -rf "$RELEASE_DIR/.build"

    # 删除旧包（保留最近 3 个版本）
    if [[ -d "$RELEASE_DIR/packages" ]]; then
        local count
        count=$(ls -1 "$RELEASE_DIR/packages"/*.tar.gz 2>/dev/null | wc -l)
        if [[ $count -gt 3 ]]; then
            log_info "Removing old packages (keeping 3 most recent)..."
            ls -t "$RELEASE_DIR/packages"/*.tar.gz | tail -n +4 | xargs -r rm -f
        fi
    fi

    log_success "Clean completed"
}

# 主命令处理
main() {
    local command="${1:-help}"
    shift || true

    case "$command" in
        build)
            cmd_build "$@"
            ;;
        publish)
            cmd_publish "$@"
            ;;
        version)
            cmd_version "$@"
            ;;
        list)
            cmd_list
            ;;
        clean)
            cmd_clean
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            log_error "Unknown command: $command"
            show_help
            exit 1
            ;;
    esac
}

main "$@"
