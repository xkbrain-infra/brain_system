# Brain Sandbox Service 构建与发布系统
# 规范: /xkagent_infra/groups/brain/spec/deployment/release_process.yaml
# 用法: make build|test|release|deploy|register|verify|help

PROJECT_NAME := brain_sandbox_service
PROJECT_ROOT := /xkagent_infra/groups/brain/projects/infrastructure/$(PROJECT_NAME)
INFRA_SERVICE := /xkagent_infra/brain/infrastructure/service/$(PROJECT_NAME)
RELEASES_DIR := $(PROJECT_ROOT)/releases

.PHONY: help build test release deploy register verify clean all

help:
	@echo "Brain Sandbox Service Build System"
	@echo "=================================="
	@echo ""
	@echo "可用目标:"
	@echo "  make build         - 校验 Python 语法"
	@echo "  make test          - 运行测试（若存在）"
	@echo "  make release       - 创建新版本 (VERSION=x.y.z)"
	@echo "  make deploy        - 部署到 infrastructure"
	@echo "  make register      - 刷新 runtime entrypoints（如需要）"
	@echo "  make verify        - 验证发布产物"
	@echo ""
	@echo "完整发布流程:"
	@echo "  make all VERSION=0.1.0"

all: build release deploy register verify
	@echo ""
	@echo "========================================"
	@echo "  发布完成: v$(VERSION)"
	@echo "========================================"
	@echo ""
	@echo "服务: brain_sandbox_service"

build:
	@echo "=== Building $(PROJECT_NAME) ==="
	@cd $(PROJECT_ROOT)/src/current && \
		find . -name "*.py" -exec python3 -m py_compile {} \; && \
		echo "✅ Python 语法验证通过"

test:
	@echo "=== Running Tests ==="
	@if [ -d "$(PROJECT_ROOT)/tests" ]; then \
		python3 -m pytest $(PROJECT_ROOT)/tests -v; \
	else \
		echo "  - 无 source tests 目录"; \
	fi

release:
	@if [ -z "$(VERSION)" ]; then \
		echo "错误: 请指定 VERSION 参数"; \
		echo "用法: make release VERSION=x.y.z"; \
		exit 1; \
	fi
	@echo "=== Releasing $(PROJECT_NAME) v$(VERSION) ==="
	@mkdir -p $(RELEASES_DIR)/v$(VERSION)/bin
	@mkdir -p $(RELEASES_DIR)/v$(VERSION)/current
	@cp -r $(PROJECT_ROOT)/src/current/* $(RELEASES_DIR)/v$(VERSION)/current/
	@cp -r $(PROJECT_ROOT)/src/bin/* $(RELEASES_DIR)/v$(VERSION)/bin/
	@if [ -d "$(PROJECT_ROOT)/tests" ]; then \
		mkdir -p $(RELEASES_DIR)/v$(VERSION)/tests; \
		cp -r $(PROJECT_ROOT)/tests/* $(RELEASES_DIR)/v$(VERSION)/tests/; \
	fi
	@rm -f $(PROJECT_ROOT)/current
	@ln -sf $(RELEASES_DIR)/v$(VERSION) $(PROJECT_ROOT)/current
	@python3 -c 'from pathlib import Path; import re; project_file = Path("$(PROJECT_ROOT)/project.yaml"); text = project_file.read_text(encoding="utf-8"); text = re.sub(r"version:\\s*[\\\"\\'\"'\"']?[^\\\"\\'\"'\"'\\n]+[\\\"\\'\"'\"']?", "version: \"$(VERSION)\"", text, count=1); project_file.write_text(text, encoding="utf-8")'
	@echo "✅ 版本创建完成: v$(VERSION)"

deploy:
	@if [ -z "$(VERSION)" ]; then \
		echo "错误: 请指定 VERSION 参数"; \
		echo "用法: make deploy VERSION=x.y.z"; \
		exit 1; \
	fi
	@echo "=== Deploying to Infrastructure ==="
	@mkdir -p $(INFRA_SERVICE)/releases/v$(VERSION)
	@cp -r $(RELEASES_DIR)/v$(VERSION)/* $(INFRA_SERVICE)/releases/v$(VERSION)/
	@rm -rf $(INFRA_SERVICE)/.previous
	@if [ -d $(INFRA_SERVICE)/current ]; then \
		mv $(INFRA_SERVICE)/current $(INFRA_SERVICE)/.previous; \
	fi
	@cp -r $(INFRA_SERVICE)/releases/v$(VERSION)/current $(INFRA_SERVICE)/current
	@mkdir -p $(INFRA_SERVICE)/bin
	@cp -r $(INFRA_SERVICE)/releases/v$(VERSION)/bin/* $(INFRA_SERVICE)/bin/
	@if [ -d "$(INFRA_SERVICE)/tests" ]; then rm -rf $(INFRA_SERVICE)/tests; fi
	@if [ -d "$(INFRA_SERVICE)/releases/v$(VERSION)/tests" ]; then \
		cp -r $(INFRA_SERVICE)/releases/v$(VERSION)/tests $(INFRA_SERVICE)/tests; \
	fi
	@chmod +x $(INFRA_SERVICE)/bin/brain_sandbox_service
	@echo "✅ 部署完成: v$(VERSION)"

register:
	@echo "=== Registering Runtime Entry Points ==="
	@echo "  - brain_sandbox_service 当前不写 supervisor / agentctl registry"
	@echo "  - 依赖既有 /xkagent_infra/brain/bin/sandboxctl wrapper 与 service bundle 路径"
	@echo "✅ 注册步骤完成（无额外变更）"

verify:
	@echo "=== Verification ==="
	@if [ -f "$(INFRA_SERVICE)/bin/brain_sandbox_service" ]; then \
		echo "✅ bin/brain_sandbox_service 存在"; \
	else \
		echo "❌ bin/brain_sandbox_service 不存在"; \
		exit 1; \
	fi
	@if [ -f "$(INFRA_SERVICE)/current/sandbox_service.py" ]; then \
		echo "✅ current/sandbox_service.py 存在"; \
	else \
		echo "❌ current/sandbox_service.py 不存在"; \
		exit 1; \
	fi
	@if [ -f "/xkagent_infra/brain/bin/sandboxctl" ]; then \
		echo "✅ /xkagent_infra/brain/bin/sandboxctl 存在"; \
	else \
		echo "❌ /xkagent_infra/brain/bin/sandboxctl 不存在"; \
		exit 1; \
	fi

clean:
	@find $(PROJECT_ROOT)/src -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	@find $(PROJECT_ROOT)/src -name "*.pyc" -delete 2>/dev/null || true
	@echo "  - 清理完成"
