#!/bin/bash
#
# Brain System Container Entrypoint
# 用途: brain/system 镜像的初始化脚本
#

set -euo pipefail

log_info() { echo "[brain-system] $1"; }

# 加载版本信息
if [[ -f /brain/RELEASE_INFO ]]; then
    # shellcheck source=/dev/null
    source /brain/RELEASE_INFO
    log_info "Brain System v${BRAIN_SYSTEM_VERSION:-unknown}"
    log_info "Build: ${BRAIN_SYSTEM_BUILD_COMMIT:-unknown}"
fi

# 执行基础镜像的启动流程
# 注意：实际服务启动由 supervisord 管理
log_info "Brain system initialized"

# 如果提供了命令，执行它；否则保持运行
if [[ $# -gt 0 ]]; then
    exec "$@"
else
    # 保持容器运行（当不作为服务运行时）
    tail -f /dev/null
fi
