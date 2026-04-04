# Brain Sandbox - Development Environment
# 用途: 开发调试环境（热重载、调试工具、读写权限）
# 路径: /xkagent_infra/groups/brain/platform/sandbox/dev/Dockerfile

FROM brain-sandbox-base:2.1.0

LABEL brain.sandbox.type="development"
LABEL brain.sandbox.version="2.1.0"

# ============================================================================
# 开发环境特定配置
# ============================================================================

ENV SANDBOX_TYPE="development"
ENV DEBUG="true"
ENV HOT_RELOAD="true"
ENV DEV_TOOLS="enabled"

# 开发工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    vim \
    nano \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

# 调试端口
EXPOSE 5678

# 启动 supervisord（brain 服务 + 项目开发环境）
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
