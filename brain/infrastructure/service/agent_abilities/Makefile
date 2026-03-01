# Makefile - Hooks 构建系统入口
# 用法: make build|test|release|rollback|help

SCRIPTS_DIR := build/scripts/hooks
HOOK_ROOT := /brain/infrastructure/service/agent_abilities

.PHONY: build test release rollback help verify

# 默认目标
help:
	@echo "Brain Hooks Build System"
	@echo "========================"
	@echo ""
	@echo "可用目标:"
	@echo "  make build      - 构建 hooks (自动发现 handlers/checkers)"
	@echo "  make test       - 运行集成测试"
	@echo "  make release    - 发布新版本"
	@echo "  make rollback   - 回滚到上一版本"
	@echo "  make verify     - 验证 hooks 状态"
	@echo "  make help       - 显示帮助"

build:
	@echo "=== Building Hooks ==="
	cd $(HOOK_ROOT) && bash $(SCRIPTS_DIR)/build.sh

test:
	@echo "=== Running Hooks Tests ==="
	cd $(HOOK_ROOT) && bash $(SCRIPTS_DIR)/test_hooks.sh

release:
	@echo "=== Releasing New Version ==="
	cd $(HOOK_ROOT) && bash $(SCRIPTS_DIR)/release.sh $(VERSION)

rollback:
	@echo "=== Rolling Back ==="
	cd $(HOOK_ROOT) && bash $(SCRIPTS_DIR)/rollback.sh $(if $(YES),--yes,)

verify:
	@echo "=== Verifying Hooks ==="
	@echo "Current version: $$(readlink $(HOOK_ROOT)/bin/hooks/current)"
	@echo "Source version: $$(readlink $(HOOK_ROOT)/src/hooks/handlers/tool_validation/current)"
	@test -f $(HOOK_ROOT)/config/versions.yaml && echo "versions.yaml: OK" || echo "versions.yaml: MISSING"
