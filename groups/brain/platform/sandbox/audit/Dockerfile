# Brain Sandbox - Audit Environment
# 用途: 审计审查、安全检查（只读、不可变、完整日志）
# 路径: /xkagent_infra/groups/brain/platform/sandbox/audit/Dockerfile

FROM brain-sandbox-base:2.1.0

LABEL brain.sandbox.type="audit"
LABEL brain.sandbox.version="2.1.0"
LABEL brain.audit="true"
LABEL brain.immutable="true"

# ============================================================================
# 审计环境特定配置
# ============================================================================

ENV SANDBOX_TYPE="audit"
ENV AUDIT_MODE="true"
ENV LOG_ALL="true"
ENV IMMUTABLE="true"

# 审计日志目录
RUN mkdir -p /workspace/audit && chmod 755 /workspace/audit

# 审计工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    strace \
    lsof \
    net-tools \
    auditd \
    && rm -rf /var/lib/apt/lists/*

# 启动 supervisord
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
