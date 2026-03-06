FROM ubuntu:24.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bat \
        build-essential \
        ca-certificates \
        curl \
        docker-compose-v2 \
        docker.io \
        fd-find \
        git \
        gnupg \
        htop \
        jq \
        openjdk-21-jre-headless \
        openssh-server \
        python3 \
        python3-pip \
        python3-venv \
        ripgrep \
        sudo \
        supervisor \
        tmux \
        tree \
        tzdata \
        unzip \
        vim \
        wget \
        zsh \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf "$(which fdfind)" /usr/local/bin/fd \
    && ln -sf "$(which batcat)" /usr/local/bin/bat

ARG UV_VERSION=0.10.6
ARG CLAUDE_CODE_VERSION=2.1.63
ARG GEMINI_CLI_VERSION=0.29.4
ARG CODEX_CLI_VERSION=0.106.0
ARG GITHUB_COPILOT_VERSION=0.0.411

RUN npm install -g \
    "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    "@google/gemini-cli@${GEMINI_CLI_VERSION}" \
    "@openai/codex@${CODEX_CLI_VERSION}" \
    "@github/copilot@${GITHUB_COPILOT_VERSION}"

RUN mkdir -p /run/sshd /var/log/supervisor \
    && echo "root:aigroup" | chpasswd \
    && ssh-keygen -A

COPY sshd_config /etc/ssh/sshd_config
COPY requirements.lock.txt /tmp/requirements.lock.txt

RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.lock.txt \
    && /opt/venv/bin/pip install --no-cache-dir "uv==${UV_VERSION}" \
    && rm /tmp/requirements.lock.txt

ENV PATH="/opt/venv/bin:$PATH"

COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# 从构建上下文复制代码（context 是仓库根目录）
COPY brain /xkagent_infra/brain
RUN ln -s /xkagent_infra/brain /brain

WORKDIR /xkagent_infra/brain

CMD ["/bin/bash", "-lc", "\
if [ -x /xkagent_infra/brain/platform/docker/scripts/container_bootstrap.sh ]; then \
    /xkagent_infra/brain/platform/docker/scripts/container_bootstrap.sh; \
else \
    echo '[bootstrap] script not found, skip'; \
fi; \
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf"]
