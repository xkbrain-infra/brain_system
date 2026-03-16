#!/bin/bash
#
# Brain System Release Publish Script
# 用途: 发布 brain/system 镜像到 registry
# 用法: ./publish.sh [version] [registry]
#

set -euo pipefail

# 获取脚本所在目录
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

# 读取版本号
VERSION_FILE="$RELEASE_DIR/VERSION"
if [[ -f "$VERSION_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$VERSION_FILE"
fi

VERSION="${1:-${VERSION:-2.1.0}}"
REGISTRY="${2:-localhost:5000}"

IMAGE_NAME="brain/system"
FULL_IMAGE_NAME="$REGISTRY/$IMAGE_NAME"

log_info "Publishing Brain System Release"
log_info "Version: $VERSION"
log_info "Registry: $REGISTRY"

# 检查镜像是否存在
if ! docker image inspect "$IMAGE_NAME:$VERSION" &>/dev/null; then
    log_error "Image not found: $IMAGE_NAME:$VERSION"
    log_info "Please build first: ./scripts/build.sh $VERSION"
    exit 1
fi

# 重新打标签（包含 registry）
log_info "Tagging image for registry..."
docker tag "$IMAGE_NAME:$VERSION" "$FULL_IMAGE_NAME:$VERSION"
docker tag "$IMAGE_NAME:$VERSION" "$FULL_IMAGE_NAME:latest"

# 推送到 registry
log_info "Pushing to registry..."
docker push "$FULL_IMAGE_NAME:$VERSION"
docker push "$FULL_IMAGE_NAME:latest"

log_success "Published: $FULL_IMAGE_NAME:$VERSION"
log_success "Published: $FULL_IMAGE_NAME:latest"

# 更新版本文件的发布记录
PUBLISH_RECORD="$RELEASE_DIR/.publish_history"
echo "$(date -Iseconds) - Published version $VERSION to $REGISTRY" >> "$PUBLISH_RECORD"

log_success "Publish completed!"
