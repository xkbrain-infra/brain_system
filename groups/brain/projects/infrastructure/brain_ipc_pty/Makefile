# Brain IPC PTY 构建与发布系统
# 规范: /xkagent_infra/groups/brain/spec/deployment/release_process.yaml

PROJECT_NAME := brain_ipc_pty
PROJECT_ROOT := /xkagent_infra/groups/brain/projects/infrastructure/$(PROJECT_NAME)
INFRA_SERVICE := /xkagent_infra/brain/infrastructure/service/$(PROJECT_NAME)
RELEASES_DIR := $(PROJECT_ROOT)/releases

.PHONY: all build release deploy verify clean

all: build release deploy verify

build:
	@echo "=== Building $(PROJECT_NAME) ==="
	@cd $(PROJECT_ROOT) && \
		make -f /xkagent_infra/brain/infrastructure/service/brain_ipc_pty/Makefile clean > /dev/null 2>&1 && \
		make -f /xkagent_infra/brain/infrastructure/service/brain_ipc_pty/Makefile > /dev/null 2>&1 && \
		echo "✅ 编译完成"

release:
	@if [ -z "$(VERSION)" ]; then \
		echo "错误: 请指定 VERSION 参数"; \
		exit 1; \
	fi
	@echo "=== Releasing $(PROJECT_NAME) v$(VERSION) ==="
	@mkdir -p $(RELEASES_DIR)/v$(VERSION)/bin
	@cp $(PROJECT_ROOT)/releases/v1.0.0/bin/brain_ipc_pty $(RELEASES_DIR)/v$(VERSION)/bin/ 2>/dev/null || \
		cp $(PROJECT_ROOT)/bin/current/brain_ipc_pty $(RELEASES_DIR)/v$(VERSION)/bin/
	@cp -r $(PROJECT_ROOT)/src $(RELEASES_DIR)/v$(VERSION)/
	@rm -f $(PROJECT_ROOT)/current
	@ln -sf $(RELEASES_DIR)/v$(VERSION) $(PROJECT_ROOT)/current
	@echo "✅ 版本创建完成: v$(VERSION)"

deploy:
	@if [ -z "$(VERSION)" ]; then \
		echo "错误: 请指定 VERSION 参数"; \
		exit 1; \
	fi
	@echo "=== Deploying $(PROJECT_NAME) v$(VERSION) ==="
	@mkdir -p $(INFRA_SERVICE)/releases/v$(VERSION)/bin
	@cp -r $(RELEASES_DIR)/v$(VERSION)/* $(INFRA_SERVICE)/releases/v$(VERSION)/
	@rm -rf $(INFRA_SERVICE)/.previous
	@if [ -d $(INFRA_SERVICE)/current ]; then \
		mv $(INFRA_SERVICE)/current $(INFRA_SERVICE)/.previous; \
	fi
	@cp -r $(INFRA_SERVICE)/releases/v$(VERSION) $(INFRA_SERVICE)/current
	@ln -sfn ../current/bin $(INFRA_SERVICE)/bin/current 2>/dev/null || true
	@echo "✅ 部署完成: v$(VERSION)"

verify:
	@echo "=== Verification ==="
	@if [ -d $(INFRA_SERVICE)/current ]; then \
		echo "✅ current 目录存在"; \
	else \
		echo "❌ current 目录不存在"; \
	fi

clean:
	@rm -rf $(PROJECT_ROOT)/build
	@rm -f $(PROJECT_ROOT)/bin/current
