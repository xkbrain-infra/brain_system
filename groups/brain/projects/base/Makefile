# Base 构建与发布系统
# 规范: /xkagent_infra/groups/brain/spec/deployment/release_process.yaml

PROJECT_NAME := base
PROJECT_ROOT := /xkagent_infra/groups/brain/projects/$(PROJECT_NAME)
INFRA_SERVICE := /xkagent_infra/brain/$(PROJECT_NAME)
RELEASES_DIR := $(PROJECT_ROOT)/releases

.PHONY: all build release deploy verify clean

all: build release deploy verify

build:
	@echo "=== Building $(PROJECT_NAME) ==="
	@echo "✅ 无需编译 (配置服务)"

release:
	@if [ -z "$(VERSION)" ]; then \
		echo "错误: 请指定 VERSION 参数"; \
		exit 1; \
	fi
	@echo "=== Releasing $(PROJECT_NAME) v$(VERSION) ==="
	@mkdir -p $(RELEASES_DIR)/v$(VERSION)
	@cp -r $(PROJECT_ROOT)/evolution $(RELEASES_DIR)/v$(VERSION)/
	@cp -r $(PROJECT_ROOT)/hooks $(RELEASES_DIR)/v$(VERSION)/
	@cp -r $(PROJECT_ROOT)/knowledge $(RELEASES_DIR)/v$(VERSION)/
	@cp -r $(PROJECT_ROOT)/mcp $(RELEASES_DIR)/v$(VERSION)/
	@cp -r $(PROJECT_ROOT)/scripts $(RELEASES_DIR)/v$(VERSION)/
	@cp -r $(PROJECT_ROOT)/skill $(RELEASES_DIR)/v$(VERSION)/
	@cp -r $(PROJECT_ROOT)/spec $(RELEASES_DIR)/v$(VERSION)/
	@cp -r $(PROJECT_ROOT)/tests $(RELEASES_DIR)/v$(VERSION)/
	@cp -r $(PROJECT_ROOT)/workflow $(RELEASES_DIR)/v$(VERSION)/
	@cp $(PROJECT_ROOT)/INIT.md.new $(RELEASES_DIR)/v$(VERSION)/ 2>/dev/null || true
	@cp $(PROJECT_ROOT)/PUBLISH_MANIFEST.yaml $(RELEASES_DIR)/v$(VERSION)/ 2>/dev/null || true
	@cp $(PROJECT_ROOT)/README.md $(RELEASES_DIR)/v$(VERSION)/ 2>/dev/null || true
	@cp $(PROJECT_ROOT)/index.yaml $(RELEASES_DIR)/v$(VERSION)/ 2>/dev/null || true
	@cp $(PROJECT_ROOT)/project.yaml $(RELEASES_DIR)/v$(VERSION)/ 2>/dev/null || true
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
	@echo "  - 备份当前版本到 .previous..."
	@rm -rf $(INFRA_SERVICE)/.previous
	@mkdir -p $(INFRA_SERVICE)/.previous
	@cp -r $(INFRA_SERVICE)/* $(INFRA_SERVICE)/.previous/ 2>/dev/null || true
	@echo "  - 清理并部署新版本..."
	@rm -rf $(INFRA_SERVICE)/evolution $(INFRA_SERVICE)/hooks $(INFRA_SERVICE)/knowledge \
		$(INFRA_SERVICE)/mcp $(INFRA_SERVICE)/scripts $(INFRA_SERVICE)/skill \
		$(INFRA_SERVICE)/spec $(INFRA_SERVICE)/tests $(INFRA_SERVICE)/workflow
	@rm -f $(INFRA_SERVICE)/INIT.md.new $(INFRA_SERVICE)/PUBLISH_MANIFEST.yaml \
		$(INFRA_SERVICE)/README.md $(INFRA_SERVICE)/index.yaml
	@cp -r $(RELEASES_DIR)/v$(VERSION)/* $(INFRA_SERVICE)/
	@echo "✅ 部署完成: v$(VERSION)"

verify:
	@echo "=== Verification ==="
	@if [ -f $(INFRA_SERVICE)/project.yaml ]; then \
		VERSION=$$(grep 'version:' $(INFRA_SERVICE)/project.yaml | head -1 | sed 's/.*version: //'); \
		echo "✅ base 已部署，版本: $$VERSION"; \
	else \
		echo "❌ project.yaml 不存在"; \
	fi

clean:
	@echo "无需清理"
