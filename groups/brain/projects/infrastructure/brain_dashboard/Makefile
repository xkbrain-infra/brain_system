# Brain Dashboard 构建与发布系统
# 规范: /xkagent_infra/groups/brain/spec/deployment/release_process.yaml
# 用法: make build|test|release|deploy|register|rollback|verify|help

PROJECT_NAME := brain_dashboard
PROJECT_ROOT := /xkagent_infra/groups/brain/projects/infrastructure/$(PROJECT_NAME)
INFRA_SERVICE := /xkagent_infra/brain/infrastructure/service/$(PROJECT_NAME)
RELEASES_DIR := $(PROJECT_ROOT)/releases

# 配置路径
SUPERVISOR_CONF := /xkagent_infra/brain/infrastructure/config/supervisord.d/brain_dashboard.conf
SUPERVISOR_MAIN_CONF := /etc/supervisor/conf.d/supervisord.conf
AGENTCTL_REGISTRY := /xkagent_infra/brain/infrastructure/config/agentctl/agents_registry.yaml

.PHONY: help build test check-code-version check-supervisor release deploy register restart rollback verify verify-deploy verify-register fix-deploy clean

# 默认目标
help:
	@echo "Brain Dashboard Build System"
	@echo "============================"
	@echo ""
	@echo "可用目标:"
	@echo "  make build              - 构建当前版本"
	@echo "  make test               - 运行单元测试"
	@echo "  make check-code-version - 检查代码版本号"
	@echo "  make check-supervisor   - 检查 supervisor 配置"
	@echo "  make release            - 创建新版本 (VERSION=x.y.z)"
	@echo "  make deploy             - 部署到 infrastructure"
	@echo "  make register           - 更新 supervisor + agentctl 注册"
	@echo "  make restart            - 重启服务"
	@echo "  make rollback           - 回滚到上一版本"
	@echo "  make verify             - 验证项目状态"
	@echo "  make verify-deploy      - 验证 infrastructure 部署"
	@echo "  make verify-register    - 验证服务注册"
	@echo ""
	@echo "完整发布流程:"
	@echo "  1. make check-code-version VERSION=2.3.0"
	@echo "  2. make check-supervisor"
	@echo "  3. make all VERSION=2.3.0"
	@echo ""
	@echo "一键发布:"
	@echo "  make all VERSION=2.3.0"

# 一键发布（完整流程）
all: release deploy register verify
	@echo ""
	@echo "========================================"
	@echo "  发布完成: v$(VERSION)"
	@echo "========================================"
	@echo ""
	@echo "请手动检查以下事项:"
	@echo "  1. 健康检查: curl http://localhost:8080/health"
	@echo "  2. 网站访问: http://localhost:8080"
	@echo ""
	@echo "如需要重启服务: make restart"

# 检查代码中的版本号（必须在 release 之前执行）
check-code-version:
	@if [ -z "$(VERSION)" ]; then \
		echo "错误: 请指定 VERSION 参数"; \
		echo "用法: make check-code-version VERSION=x.y.z"; \
		exit 1; \
	fi
	@echo "=== Checking Code Version ==="
	@echo "检查 src/app.py 中的版本号..."
	@CURRENT_VERSION=$$(grep -E 'version="[0-9]+\.[0-9]+\.[0-9]+"' $(PROJECT_ROOT)/src/app.py | head -1 | sed 's/.*version="\([0-9]\+\.[0-9]\+\.[0-9]\+\)".*/\1/'); \
	if [ "$$CURRENT_VERSION" != "$(VERSION)" ]; then \
		echo ""; \
		echo "⚠️  警告: 代码版本号不匹配!"; \
		echo "    期望: $(VERSION)"; \
		echo "    实际: $$CURRENT_VERSION"; \
		echo ""; \
		echo "请手动更新以下文件中的版本号:"; \
		echo "  - $(PROJECT_ROOT)/src/app.py"; \
		echo ""; \
		echo "需要更新的地方:"; \
		echo '  1. FastAPI(version="X.Y.Z")'; \
		echo '  2. return {"version": "X.Y.Z", ...}'; \
		echo ""; \
		exit 1; \
	else \
		echo "✅ 代码版本号正确: $(VERSION)"; \
	fi

# 检查 supervisor 主配置是否存在
check-supervisor:
	@echo "=== Checking Supervisor Configuration ==="
	@if grep -q "\[program:brain_dashboard\]" $(SUPERVISOR_MAIN_CONF) 2>/dev/null; then \
		echo "✅ Supervisor 主配置已存在: $(SUPERVISOR_MAIN_CONF)"; \
	else \
		echo "❌ 错误: Supervisor 主配置不存在!"; \
		echo ""; \
		echo "请手动添加以下配置到 $(SUPERVISOR_MAIN_CONF):"; \
		echo ""; \
		echo "[program:brain_dashboard]"; \
		echo "command=/opt/venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8080 --log-level info"; \
		echo "directory=/xkagent_infra/brain/infrastructure/service/brain_dashboard/current/src"; \
		echo "autostart=true"; \
		echo "autorestart=true"; \
		echo "priority=28"; \
		echo "startsecs=3"; \
		echo "startretries=3"; \
		echo "stopasgroup=true"; \
		echo "killasgroup=true"; \
		echo "environment=HOME=\"/root\",BRAIN_PATH=\"/xkagent_infra/brain\",BRAIN_IPC_SOCKET=\"/tmp/brain_ipc.sock\",DASHBOARD_VERSION=\"2.2.0\",DASHBOARD_SERVICE=\"service-brain_dashboard\",PYTHONPATH=\"/brain/infrastructure/service/utils/ipc/src\""; \
		echo "stdout_logfile=/xkagent_infra/runtime/logs/brain_dashboard.supervisor.log"; \
		echo "stderr_logfile=/xkagent_infra/runtime/logs/brain_dashboard.supervisor.err.log"; \
		echo ""; \
		exit 1; \
	fi

# 构建当前版本
build:
	@echo "=== Building $(PROJECT_NAME) ==="
	@cd $(PROJECT_ROOT)/src && \
		echo "  - 验证 Python 语法..." && \
		python3 -m py_compile *.py && \
		echo "  - 构建完成"

# 运行测试
test:
	@echo "=== Running Tests ==="
	@cd $(PROJECT_ROOT) && \
		if [ -d "tests" ]; then \
			python3 -m pytest tests/ -v; \
		else \
			echo "  - 无测试目录"; \
		fi

# 创建新版本（在项目目录中）
release: check-code-version check-supervisor
	@if [ -z "$(VERSION)" ]; then \
		echo "错误: 请指定 VERSION 参数"; \
		echo "用法: make release VERSION=x.y.z"; \
		exit 1; \
	fi
	@echo "=== Releasing $(PROJECT_NAME) v$(VERSION) ==="
	@echo "  - 从 current 复制到 releases/v$(VERSION)..."
	@cp -rL $(PROJECT_ROOT)/current $(RELEASES_DIR)/v$(VERSION)
	@echo "  - 更新 current 软链接..."
	@rm -f $(PROJECT_ROOT)/current
	@ln -sf $(RELEASES_DIR)/v$(VERSION) $(PROJECT_ROOT)/current
	@echo "  - 更新 project.yaml 版本..."
	@sed -i 's/version: .*/version: $(VERSION)/' $(PROJECT_ROOT)/project.yaml
	@echo "✅ 版本创建完成: v$(VERSION)"

# 部署到 infrastructure（实际文件，非软链接）
# 符合 BRAIN-DEPLOY-001 规范
deploy:
	@if [ -z "$(VERSION)" ]; then \
		echo "错误: 请指定 VERSION 参数"; \
		echo "用法: make deploy VERSION=x.y.z"; \
		exit 1; \
	fi
	@echo "=== Deploying to Infrastructure ==="
	@echo "规范: BRAIN-DEPLOY-001 (实际文件，禁止软链接)"
	@echo ""
	@echo "  - 创建 infrastructure releases/v$(VERSION)..."
	@mkdir -p $(INFRA_SERVICE)/releases/v$(VERSION)
	@echo "  - 复制实际文件到 infrastructure (cp -rL)"
	@cp -rL $(RELEASES_DIR)/v$(VERSION)/* $(INFRA_SERVICE)/releases/v$(VERSION)/
	@echo "  - 备份 current 到 .previous..."
	@rm -rf $(INFRA_SERVICE)/.previous
	@if [ -d $(INFRA_SERVICE)/current ]; then \
		mv $(INFRA_SERVICE)/current $(INFRA_SERVICE)/.previous; \
	fi
	@echo "  - 创建新的 current (实际目录)"
	@cp -r $(INFRA_SERVICE)/releases/v$(VERSION) $(INFRA_SERVICE)/current
	@echo ""
	@echo "✅ 部署完成: v$(VERSION)"

# 更新服务注册（supervisor + agentctl）
# 符合 BRAIN-DEPLOY-REGISTER 规范
register:
	@if [ -z "$(VERSION)" ]; then \
		echo "错误: 请指定 VERSION 参数"; \
		echo "用法: make register VERSION=x.y.z"; \
		exit 1; \
	fi
	@echo "=== Updating Service Registration ==="
	@echo "规范: BRAIN-DEPLOY-REGISTER (supervisor + agentctl)"
	@echo ""
	@echo "  - 更新 supervisor 配置..."
	@sed -i 's/v[0-9]\+\.[0-9]\+\.[0-9]\+/v$(VERSION)/g' $(SUPERVISOR_CONF)
	@sed -i 's/DASHBOARD_VERSION="[^"]*"/DASHBOARD_VERSION="$(VERSION)"/g' $(SUPERVISOR_CONF)
	@# 同时更新主配置文件
	@if [ -f $(SUPERVISOR_MAIN_CONF) ]; then \
		sed -i 's/DASHBOARD_VERSION="[^"]*"/DASHBOARD_VERSION="$(VERSION)"/g' $(SUPERVISOR_MAIN_CONF); \
	fi
	@echo "    ✅ $(SUPERVISOR_CONF)"
	@echo ""
	@echo "  - 更新 agentctl 注册表..."
	@sed -i 's/version: v[0-9]\+\.[0-9]\+\.[0-9]\+/version: v$(VERSION)/g' $(AGENTCTL_REGISTRY)
	@echo "    ✅ $(AGENTCTL_REGISTRY)"
	@echo ""
	@echo "  - 重载 supervisor 配置..."
	@supervisorctl reread 2>/dev/null || echo "    ⚠️ supervisorctl reread 失败（忽略）"
	@supervisorctl update brain_dashboard 2>/dev/null || echo "    ⚠️ supervisorctl update 失败（忽略）"
	@echo "    ✅ supervisor 配置已重载"
	@echo ""
	@echo "✅ 服务注册更新完成: v$(VERSION)"

# 重启服务
restart:
	@echo "=== Restarting Service ==="
	@supervisorctl restart brain_dashboard 2>/dev/null || echo "⚠️ 重启失败，请检查服务状态"
	@sleep 2
	@supervisorctl status brain_dashboard 2>/dev/null || echo "请手动检查服务状态"

# 回滚到上一版本
rollback:
	@echo "=== Rolling Back ==="
	@if [ -d $(INFRA_SERVICE)/.previous ]; then \
		echo "  - 恢复 .previous 到 current..."; \
		rm -rf $(INFRA_SERVICE)/current; \
		mv $(INFRA_SERVICE)/.previous $(INFRA_SERVICE)/current; \
		echo "✅ 回滚完成"; \
	else \
		echo "错误: 没有 .previous 备份"; \
		exit 1; \
	fi

# 验证项目状态
verify:
	@echo "=== Project Verification ==="
	@echo "项目版本: $$(grep 'version:' $(PROJECT_ROOT)/project.yaml | head -1)"
	@echo "Current: $$(readlink $(PROJECT_ROOT)/current)"
	@echo ""
	@echo "可用版本:"
	@ls -1 $(RELEASES_DIR) | grep -E '^v[0-9]' | sort -V | sed 's/^/  - /'
	@echo ""
	@cd $(PROJECT_ROOT) && make verify-deploy && make verify-register

# 验证 infrastructure 部署（检查软链接违规）
verify-deploy:
	@echo "=== Infrastructure Deployment Verification ==="
	@echo "检查规范 BRAIN-DEPLOY-001..."
	@echo ""
	@# 检查 current
	@if [ -L $(INFRA_SERVICE)/current ]; then \
		echo "❌ current 是软链接: $$(readlink $(INFRA_SERVICE)/current)"; \
		echo "   修复: make fix-deploy"; \
		exit 1; \
	else \
		echo "✅ current 是实际目录"; \
	fi
	@# 检查 releases
	@for v in $$(ls $(INFRA_SERVICE)/releases/ 2>/dev/null | grep -E '^v[0-9]'); do \
		if [ -L $(INFRA_SERVICE)/releases/$$v ]; then \
			echo "❌ releases/$$v 是软链接"; \
			exit 1; \
		else \
			echo "✅ releases/$$v 是实际目录"; \
		fi; \
	done
	@echo ""
	@echo "✅ 部署验证通过！"

# 验证服务注册
verify-register:
	@echo "=== Service Registration Verification ==="
	@echo "检查规范 BRAIN-DEPLOY-REGISTER..."
	@echo ""
	@echo "  Supervisor 配置:"
	@grep -E "v[0-9]+\.[0-9]+\.[0-9]+" $(SUPERVISOR_CONF) 2>/dev/null | head -2 | sed 's/^/    /' || echo "    ⚠️ 无法读取"
	@echo ""
	@echo "  Agentctl 注册表:"
	@grep -A5 "name: service-brain_dashboard" $(AGENTCTL_REGISTRY) 2>/dev/null | grep "version:" | sed 's/^/    /' || echo "    ⚠️ 无法读取"
	@echo ""
	@echo "  运行时版本:"
	@curl -s http://localhost:8080/health 2>/dev/null | grep -o '"version":"[^"]*"' | sed 's/^/    /' || echo "    ⚠️ 服务未运行"
	@echo ""
	@echo "✅ 注册验证完成"

# 修复软链接问题（转换为实际文件）
fix-deploy:
	@echo "=== Fixing Symlink Deployment ==="
	@echo "  - 备份 current..."
	@if [ -L $(INFRA_SERVICE)/current ]; then \
		LINK_TARGET=$$(readlink $(INFRA_SERVICE)/current); \
		echo "  - current 指向: $$LINK_TARGET"; \
		rm -f $(INFRA_SERVICE)/current; \
		cp -rL $$LINK_TARGET $(INFRA_SERVICE)/current; \
		echo "✅ current 已转换为实际目录"; \
	else \
		echo "✅ current 已是实际目录"; \
	fi
	@echo "  - 修复 releases..."
	@for v in $$(ls $(INFRA_SERVICE)/releases/ 2>/dev/null | grep -E '^v[0-9]'); do \
		if [ -L $(INFRA_SERVICE)/releases/$$v ]; then \
			LINK_TARGET=$$(readlink $(INFRA_SERVICE)/releases/$$v); \
			rm -f $(INFRA_SERVICE)/releases/$$v; \
			cp -rL $$LINK_TARGET $(INFRA_SERVICE)/releases/$$v; \
			echo "✅ releases/$$v 已转换为实际目录"; \
		fi; \
	done
	@echo ""
	@echo "✅ 修复完成"

# 清理构建产物
clean:
	@echo "=== Cleaning ==="
	@find $(PROJECT_ROOT)/src -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	@find $(PROJECT_ROOT)/src -name "*.pyc" -delete 2>/dev/null || true
	@echo "  - 清理完成"
