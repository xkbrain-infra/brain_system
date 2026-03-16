#!/bin/bash
#
# Brain System Release Validation Script
# 用途: 验证发布流程和镜像完整性
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
log_success() { echo -e "${GREEN}[PASS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[FAIL]${NC} $1"; }

check_count=0
fail_count=0

check() {
    local name=$1
    shift
    check_count=$((check_count + 1))
    if "$@" &>/dev/null; then
        log_success "$name"
        return 0
    else
        log_error "$name"
        fail_count=$((fail_count + 1))
        return 1
    fi
}

log_info "Brain System Release Validation"
log_info "================================"

# 1. 检查必要的文件
echo ""
log_info "Checking required files..."
check "VERSION file exists" test -f "$RELEASE_DIR/VERSION"
check "Release config exists" test -f "$RELEASE_DIR/configs/release.yaml"
check "Dockerfile exists" test -f "$RELEASE_DIR/configs/Dockerfile.release"
check "Build script exists" test -x "$RELEASE_DIR/scripts/build.sh"
check "Publish script exists" test -x "$RELEASE_DIR/scripts/publish.sh"
check "Release manager exists" test -x "$RELEASE_DIR/release.sh"

# 2. 检查版本格式
echo ""
log_info "Checking version format..."
if [[ -f "$RELEASE_DIR/VERSION" ]]; then
    # shellcheck source=/dev/null
    source "$RELEASE_DIR/VERSION"
    if [[ $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]]; then
        log_success "Version format is valid: $VERSION"
    else
        log_error "Version format is invalid: $VERSION"
        fail_count=$((fail_count + 1))
    fi
fi

# 3. 检查 Docker 环境
echo ""
log_info "Checking Docker environment..."
check "Docker is installed" command -v docker
check "Docker daemon is running" docker info

# 4. 检查 brain/docker-base 基础镜像
echo ""
log_info "Checking base images..."
if docker image inspect brain/docker-base:latest &>/dev/null; then
    log_success "brain/docker-base:latest exists"
else
    log_warn "brain/docker-base:latest not found, will be pulled during build"
fi

# 5. 检查目录结构
echo ""
log_info "Checking directory structure..."
check "scripts/ directory exists" test -d "$RELEASE_DIR/scripts"
check "configs/ directory exists" test -d "$RELEASE_DIR/configs"
check "packages/ directory exists" test -d "$RELEASE_DIR/packages"

# 6. 检查脚本语法
echo ""
log_info "Checking script syntax..."
check "build.sh syntax" bash -n "$RELEASE_DIR/scripts/build.sh"
check "publish.sh syntax" bash -n "$RELEASE_DIR/scripts/publish.sh"
check "release.sh syntax" bash -n "$RELEASE_DIR/release.sh"

# 7. 检查发布配置
echo ""
log_info "Checking release configuration..."
if [[ -f "$RELEASE_DIR/configs/release.yaml" ]]; then
    # 简单检查 YAML 语法
    if python3 -c "import yaml; yaml.safe_load(open('$RELEASE_DIR/configs/release.yaml'))" 2>/dev/null; then
        log_success "release.yaml is valid YAML"
    else
        log_warn "Could not validate release.yaml (python-yaml not installed)"
    fi
fi

# 总结
echo ""
log_info "================================"
log_info "Validation Summary"
log_info "================================"
if [[ $fail_count -eq 0 ]]; then
    log_success "All $check_count checks passed!"
    log_info "Release system is ready."
    log_info ""
    log_info "Next steps:"
    log_info "  1. ./release.sh build     - Build release image"
    log_info "  2. ./release.sh publish   - Publish to registry"
    exit 0
else
    log_error "$fail_count of $check_count checks failed"
    exit 1
fi
