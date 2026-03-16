#!/bin/bash
#
# Brain System Release Build Script
# 用途: 构建 brain/system 发布镜像
# 用法: ./build.sh [version]
#

set -euo pipefail

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_DIR="$(dirname "$SCRIPT_DIR")"
BRAIN_DIR="/brain"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 读取版本号
VERSION_FILE="$RELEASE_DIR/VERSION"
if [[ -f "$VERSION_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$VERSION_FILE"
else
    log_error "VERSION file not found: $VERSION_FILE"
    exit 1
fi

# 允许命令行覆盖版本号
VERSION="${1:-${VERSION:-2.1.0}}"

# 构建元数据
BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
BUILD_COMMIT=$(cd "$BRAIN_DIR" && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
BUILD_BRANCH=$(cd "$BRAIN_DIR" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

log_info "Building Brain System Release"
log_info "Version: $VERSION"
log_info "Build Date: $BUILD_DATE"
log_info "Commit: $BUILD_COMMIT"
log_info "Branch: $BUILD_BRANCH"

# 创建构建目录
BUILD_DIR="$RELEASE_DIR/.build"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# 准备发布内容
log_info "Preparing release content..."

# 复制核心组件到构建目录
copy_component() {
    local src=$1
    local dst=$2
    local name=$3

    if [[ -d "$src" ]]; then
        log_info "Copying $name from $src"
        mkdir -p "$dst"
        rsync -av --exclude='.git' \
                  --exclude='__pycache__' \
                  --exclude='*.pyc' \
                  --exclude='node_modules' \
                  --exclude='.claude' \
                  --exclude='.codex' \
                  --exclude='tmp' \
                  --exclude='logs' \
                  --exclude='secrets' \
                  "$src/" "$dst/"
    else
        log_warn "Source directory not found: $src"
    fi
}

# 复制组件
copy_component "$BRAIN_DIR/base" "$BUILD_DIR/brain/base" "base"
copy_component "$BRAIN_DIR/infrastructure" "$BUILD_DIR/brain/infrastructure" "infrastructure"
copy_component "$BRAIN_DIR/platform/bin" "$BUILD_DIR/brain/platform/bin" "platform/bin"
copy_component "$BRAIN_DIR/runtime" "$BUILD_DIR/brain/runtime" "runtime"

# 复制发布脚本
copy_component "$RELEASE_DIR/scripts" "$BUILD_DIR/brain/platform/release/scripts" "release scripts"

# 创建版本信息文件
cat > "$BUILD_DIR/brain/RELEASE_INFO" << EOF
BRAIN_SYSTEM_VERSION=$VERSION
BRAIN_SYSTEM_BUILD_DATE=$BUILD_DATE
BRAIN_SYSTEM_BUILD_COMMIT=$BUILD_COMMIT
BRAIN_SYSTEM_BUILD_BRANCH=$BUILD_BRANCH
EOF

log_info "Release content prepared at $BUILD_DIR"

# 构建 Docker 镜像
log_info "Building Docker image..."

IMAGE_NAME="brain/system"
DOCKERFILE="$RELEASE_DIR/configs/Dockerfile.release"

docker build \
    --build-arg VERSION="$VERSION" \
    --build-arg BUILD_DATE="$BUILD_DATE" \
    --build-arg BUILD_COMMIT="$BUILD_COMMIT" \
    --build-arg BUILD_BRANCH="$BUILD_BRANCH" \
    -t "$IMAGE_NAME:$VERSION" \
    -f "$DOCKERFILE" \
    "$BUILD_DIR"

# 打标签
docker tag "$IMAGE_NAME:$VERSION" "$IMAGE_NAME:latest"

log_success "Docker image built: $IMAGE_NAME:$VERSION"
log_success "Tagged as: $IMAGE_NAME:latest"

# 保存镜像到 packages 目录（可选，用于离线分发）
log_info "Saving image to packages directory..."
mkdir -p "$RELEASE_DIR/packages"
docker save "$IMAGE_NAME:$VERSION" | gzip > "$RELEASE_DIR/packages/brain-system-${VERSION}.tar.gz"
log_success "Image saved to: packages/brain-system-${VERSION}.tar.gz"

# 生成 manifest
MANIFEST_FILE="$RELEASE_DIR/packages/manifest-${VERSION}.yaml"
cat > "$MANIFEST_FILE" << EOF
release:
  name: brain-system
  version: $VERSION
  build_date: $BUILD_DATE
  commit: $BUILD_COMMIT
  branch: $BUILD_BRANCH
  image: $IMAGE_NAME:$VERSION

components:
  - name: base
    path: brain/base
    description: "Core specifications and standards"
  - name: infrastructure
    path: brain/infrastructure
    description: "Infrastructure components"
  - name: platform
    path: brain/platform/bin
    description: "Platform utilities"
  - name: runtime
    path: brain/runtime
    description: "Runtime configuration"

artifacts:
  image: $IMAGE_NAME:$VERSION
  tarball: packages/brain-system-${VERSION}.tar.gz
  manifest: packages/manifest-${VERSION}.yaml
EOF

log_success "Manifest generated: $MANIFEST_FILE"

# 清理构建目录
rm -rf "$BUILD_DIR"
log_info "Build directory cleaned"

log_success "Build completed successfully!"
log_info "Image: $IMAGE_NAME:$VERSION"
log_info "To publish, run: ./scripts/publish.sh $VERSION"
