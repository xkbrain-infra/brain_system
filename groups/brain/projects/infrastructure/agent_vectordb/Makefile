# Agent VectorDB 构建与发布系统
# 规范: /xkagent_infra/groups/brain/spec/deployment/release_process.yaml

PROJECT_NAME := agent_vectordb
PROJECT_ROOT := /xkagent_infra/groups/brain/projects/infrastructure/$(PROJECT_NAME)
INFRA_SERVICE := /xkagent_infra/brain/infrastructure/service/$(PROJECT_NAME)
RELEASES_DIR := $(PROJECT_ROOT)/releases

.PHONY: all build release deploy verify clean

all: build release deploy verify

build:
	@echo "=== Building $(PROJECT_NAME) ==="
	@echo "✅ 无需编译 (Python 服务)"

release:
	@if [ -z "$(VERSION)" ]; then \
		echo "错误: 请指定 VERSION 参数"; \
		exit 1; \
	fi
	@echo "=== Releasing $(PROJECT_NAME) v$(VERSION) ==="
	@mkdir -p $(RELEASES_DIR)/v$(VERSION)
	@cp -r $(PROJECT_ROOT)/src/* $(RELEASES_DIR)/v$(VERSION)/
	@rm -f $(PROJECT_ROOT)/current
	@ln -sf $(RELEASES_DIR)/v$(VERSION) $(PROJECT_ROOT)/current
	@sed -i 's/version: .*/version: $(VERSION)/' $(PROJECT_ROOT)/project.yaml
	@echo "✅ 版本创建完成: v$(VERSION)"

deploy:
	@if [ -z "$(VERSION)" ]; then \
		echo "错误: 请指定 VERSION 参数"; \
		exit 1; \
	fi
	@echo "=== Deploying $(PROJECT_NAME) v$(VERSION) ==="
	@mkdir -p $(INFRA_SERVICE)/releases/v$(VERSION)
	@cp -rL $(RELEASES_DIR)/v$(VERSION)/* $(INFRA_SERVICE)/releases/v$(VERSION)/
	@rm -rf $(INFRA_SERVICE)/.previous
	@if [ -d $(INFRA_SERVICE)/current ]; then \
		mv $(INFRA_SERVICE)/current $(INFRA_SERVICE)/.previous; \
	fi
	@cp -r $(INFRA_SERVICE)/releases/v$(VERSION) $(INFRA_SERVICE)/current
	@echo "✅ 部署完成: v$(VERSION)"

verify:
	@echo "=== Verification ==="
	@if [ -d $(INFRA_SERVICE)/current ]; then \
		echo "✅ current 目录存在"; \
	else \
		echo "❌ current 目录不存在"; \
	fi

clean:
	@echo "无需清理"
