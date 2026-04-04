# Brain Sandbox - Staging Environment
# 用途: 预发布验证（生产-like、稳定性测试）
# 路径: /xkagent_infra/groups/brain/platform/sandbox/staging/Dockerfile

FROM brain-sandbox-base:2.1.0

LABEL brain.sandbox.type="staging"
LABEL brain.sandbox.version="2.1.0"

# ============================================================================
# 预发布环境特定配置
# ============================================================================

ENV SANDBOX_TYPE="staging"
ENV STAGING="true"
ENV PROD_LIKE="true"
ENV SMOKE_TEST="enabled"

# 生产优化配置
ENV PYTHONDONTWRITEBYTECODE="1"
ENV PYTHONUNBUFFERED="1"

EXPOSE 8080

# 启动 supervisord
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
