# Brain Sandbox - Testing Environment
# 用途: 自动化测试、集成测试（只读、自动运行测试）
# 路径: /xkagent_infra/groups/brain/platform/sandbox/test/Dockerfile

FROM brain-sandbox-base:2.1.0

LABEL brain.sandbox.type="testing"
LABEL brain.sandbox.version="2.1.0"

# ============================================================================
# 测试环境特定配置
# ============================================================================

ENV SANDBOX_TYPE="testing"
ENV TESTING="true"
ENV PYTEST_CURRENT_TEST="1"
ENV COVERAGE_ENABLED="true"

# 测试工具
RUN pip install --no-cache-dir \
    pytest \
    pytest-asyncio \
    pytest-cov \
    pytest-xdist \
    coverage \
    hypothesis

# 启动 supervisord
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
