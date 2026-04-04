# Brain Sandbox Base Image
# 基于 brain/system 发布镜像构建，消费 brain 的发布版本
# 用途: 通用基础层，所有 sandbox 类型继承
# 路径: /xkagent_infra/groups/brain/platform/sandbox/base/Dockerfile

# 使用特定版本的 brain/system 镜像
# 本地开发: brain/system:2.1.0
# GitHub Actions: ghcr.io/xkbrain-infra/brain-system:2.1.0
ARG BRAIN_VERSION=2.1.0
ARG BRAIN_IMAGE=brain/system
FROM ${BRAIN_IMAGE}:${BRAIN_VERSION}

# ============================================================================
# Sandbox 通用配置
# ============================================================================

# Sandbox 工作目录
WORKDIR /workspace

# 创建标准目录结构
RUN mkdir -p \
    /workspace/project \
    /workspace/data \
    /workspace/logs \
    /workspace/tmp \
    /workspace/cache

# Sandbox 环境变量
ENV SANDBOX_MODE="full"
ENV SANDBOX_VERSION="2.1.0"
ENV SANDBOX_TYPE="base"

# Brain 环境变量（继承自 brain/system 镜像）
ENV BRAIN_PATH="/brain"
ENV BRAIN_GROUPS="/groups"
ENV BRAIN_INFRA="/brain/infrastructure"

# ============================================================================
# Claude CLI — Agent 运行时
# ============================================================================

# 安装 claude CLI（固定版本，保证所有 sandbox 行为一致）
RUN npm install -g @anthropic-ai/claude-code@2.1.77 --no-audit --no-fund

# 预置 .claude/settings.json：
#   - ANTHROPIC_BASE_URL 指向 XKAgentInfra 内的 brain_agent_proxy
#   - 加入 xk-agent-infra-net 后可直接用容器名解析
#   - 各项目 sandbox 可通过 settings.local.json 覆盖
RUN mkdir -p /root/.claude && cat > /root/.claude/settings.json <<'EOF'
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://XKAgentInfra:8210",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"
  },
  "language": "中文",
  "spinnerTipsEnabled": false
}
EOF

# 启动 supervisord（继承 brain/docker-base 的服务）
# 注意：不覆盖 CMD，使用镜像默认的 supervisord 启动
