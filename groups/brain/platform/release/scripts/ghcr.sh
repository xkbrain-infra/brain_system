#!/bin/bash
#
# GitHub Container Registry Helper
# 用途: 简化 ghcr.io 镜像的拉取和使用
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 配置
REGISTRY="ghcr.io"
ORG="xkbrain-infra"

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

# 显示帮助
show_help() {
    cat << EOF
GitHub Container Registry Helper

Usage: $0 <command> [options]

Commands:
    login                   Login to ghcr.io
    pull <image> [version]  Pull image from ghcr.io
    use-local               Use local images (default)
    use-ghcr                Use ghcr.io images
    status                  Show current configuration

Images:
    brain-system            Brain System release image
    brain-sandbox-base      Sandbox base image
    brain-sandbox-dev       Sandbox dev environment
    brain-sandbox-test      Sandbox test environment
    brain-sandbox-staging   Sandbox staging environment
    brain-sandbox-audit     Sandbox audit environment

Examples:
    $0 login                                    # Login to ghcr.io
    $0 pull brain-system 2.1.0                  # Pull specific version
    $0 pull brain-sandbox-dev latest            # Pull dev sandbox
    $0 use-ghcr                                 # Switch to GitHub images

EOF
}

# 登录 ghcr
cmd_login() {
    log_info "Logging into $REGISTRY..."
    echo "Please provide your GitHub Personal Access Token"
    echo "Token needs: read:packages, write:packages scopes"
    echo ""
    docker login $REGISTRY -u USERNAME
}

# 拉取镜像
cmd_pull() {
    local image=$1
    local version="${2:-latest}"

    local full_image="$REGISTRY/$ORG/$image:$version"
    log_info "Pulling $full_image..."
    docker pull "$full_image"
    log_success "Pulled: $full_image"
}

# 使用本地镜像
cmd_use_local() {
    log_info "Switching to local images..."

    # 更新 Sandbox Dockerfiles 使用本地镜像
    find /xkagent_infra/groups/brain/platform/sandbox -name "Dockerfile" -exec sed -i \
        -e 's|ARG BRAIN_IMAGE=.*|ARG BRAIN_IMAGE=brain/system|' \
        -e "s|FROM ghcr.io/.*/brain-system|FROM brain/system|" \
        {} \;

    log_success "Now using local images:"
    log_info "  brain/system:<version>"
    log_info "  brain/sandbox-base:<version>"
}

# 使用 ghcr 镜像
cmd_use_ghcr() {
    log_info "Switching to GitHub Container Registry images..."

    local version
    version=$(cat /xkagent_infra/groups/brain/platform/release/VERSION | grep VERSION= | cut -d= -f2)

    # 更新 Sandbox Dockerfiles 使用 ghcr 镜像
    find /xkagent_infra/groups/brain/platform/sandbox -name "Dockerfile" -exec sed -i \
        -e "s|ARG BRAIN_IMAGE=.*|ARG BRAIN_IMAGE=$REGISTRY/$ORG/brain-system|" \
        -e "s|FROM brain/system|FROM $REGISTRY/$ORG/brain-system|" \
        {} \;

    log_success "Now using ghcr.io images:"
    log_info "  $REGISTRY/$ORG/brain-system:$version"
    log_info "  $REGISTRY/$ORG/brain-sandbox-base:$version"
}

# 显示状态
cmd_status() {
    log_info "Current Configuration:"
    echo ""

    # 检查 Docker 登录状态
    if grep -q "$REGISTRY" ~/.docker/config.json 2>/dev/null; then
        log_success "Logged into $REGISTRY"
    else
        log_warn "Not logged into $REGISTRY"
    fi

    echo ""
    log_info "Available images locally:"
    docker images --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}" | grep -E "(brain-system|brain-sandbox)" || echo "  None"

    echo ""
    log_info "Dockerfiles configured for:"
    local dockerfile="/xkagent_infra/groups/brain/platform/sandbox/base/Dockerfile"
    if grep -q "$REGISTRY" "$dockerfile" 2>/dev/null; then
        echo "  GitHub Container Registry ($REGISTRY)"
    else
        echo "  Local images"
    fi
}

# 主命令处理
main() {
    local command="${1:-help}"
    shift || true

    case "$command" in
        login)
            cmd_login
            ;;
        pull)
            if [[ $# -lt 1 ]]; then
                log_error "Please specify image name"
                show_help
                exit 1
            fi
            cmd_pull "$@"
            ;;
        use-local)
            cmd_use_local
            ;;
        use-ghcr)
            cmd_use_ghcr
            ;;
        status)
            cmd_status
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
