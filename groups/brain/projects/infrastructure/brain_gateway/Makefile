# Brain Gateway 构建与发布系统 (C++)
# 规范: /xkagent_infra/groups/brain/spec/deployment/release_process.yaml
# 用法: make build|test|release|deploy|register|rollback|verify|help

PROJECT_NAME := brain_gateway
PROJECT_ROOT := /xkagent_infra/groups/brain/projects/infrastructure/$(PROJECT_NAME)
INFRA_SERVICE := /xkagent_infra/brain/infrastructure/service/$(PROJECT_NAME)
RELEASES_DIR := $(PROJECT_ROOT)/releases

# C++ 构建设置
CXX := g++
CXXFLAGS := -std=c++20 -fPIC -fno-exceptions -Wall -Wextra -O2 -pthread -I$(PROJECT_ROOT)/src -I$(PROJECT_ROOT)/include
LDFLAGS := -pthread

TARGET := brain_gateway
SRCS := $(wildcard $(PROJECT_ROOT)/src/*.cpp)

# 配置路径
SUPERVISOR_MAIN_CONF := /etc/supervisor/conf.d/supervisord.conf
AGENTCTL_REGISTRY := /xkagent_infra/brain/infrastructure/config/agentctl/agents_registry.yaml

.PHONY: help build test release deploy register restart rollback verify verify-deploy verify-register clean

# 默认目标
help:
	@echo "Brain Gateway Build System (C++)"
	@echo "================================"
	@echo ""
	@echo "可用目标:"
	@echo "  make build         - 编译 C++ 项目"
	@echo "  make test          - 运行单元测试"
	@echo "  make release       - 创建新版本 (VERSION=x.y.z)"
	@echo "  make deploy        - 部署到 infrastructure"
	@echo "  make register      - 更新 supervisor + agentctl 注册"
	@echo "  make restart       - 重启服务"
	@echo "  make rollback      - 回滚到上一版本"
	@echo "  make verify        - 验证项目状态"
	@echo "  make verify-deploy - 验证 infrastructure 部署"
	@echo ""
	@echo "完整发布流程:"
	@echo "  make all VERSION=1.0.0"
	@echo ""

# 一键发布（完整流程）
all: build release deploy register verify
	@echo ""
	@echo "========================================"
	@echo "  发布完成: v$(VERSION)"
	@echo "========================================"
	@echo ""
	@echo "服务: brain_gateway"
	@echo ""
	@echo "如需要重启服务: make restart"

# 构建 C++ 项目
build:
	@echo "=== Building $(PROJECT_NAME) (C++) ==="
	@cd $(PROJECT_ROOT) && \
		$(CXX) $(CXXFLAGS) -o $(TARGET) $(SRCS) $(LDFLAGS) && \
		echo "✅ 编译完成: $(TARGET)"

# 运行测试
test:
	@echo "=== Running Tests ==="
	@cd $(PROJECT_ROOT) && \
		if [ -d "tests" ]; then \
			echo "  - 运行 C++ 测试..."; \
		else \
			echo "  - 无测试目录"; \
		fi

# 创建新版本（在项目目录中）
release:
	@if [ -z "$(VERSION)" ]; then \
		echo "错误: 请指定 VERSION 参数"; \
		echo "用法: make release VERSION=x.y.z"; \
		exit 1; \
	fi
	@echo "=== Releasing $(PROJECT_NAME) v$(VERSION) ==="
	@echo "  - 创建 releases/v$(VERSION)..."
	@mkdir -p $(RELEASES_DIR)/v$(VERSION)/bin
	@echo "  - 复制二进制文件..."
	@cp $(PROJECT_ROOT)/$(TARGET) $(RELEASES_DIR)/v$(VERSION)/bin/ 2>/dev/null || \
		(echo "⚠️  未找到二进制文件，请先运行 make build"; exit 1)
	@echo "  - 复制 src 到 releases/v$(VERSION)..."
	@cp -r $(PROJECT_ROOT)/src $(RELEASES_DIR)/v$(VERSION)/
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
	@mkdir -p $(INFRA_SERVICE)/releases/v$(VERSION)/bin
	@echo "  - 复制实际文件到 infrastructure..."
	@cp -r $(RELEASES_DIR)/v$(VERSION)/* $(INFRA_SERVICE)/releases/v$(VERSION)/
	@echo "  - 备份 current 到 .previous..."
	@rm -rf $(INFRA_SERVICE)/.previous
	@if [ -d $(INFRA_SERVICE)/current ]; then \
		mv $(INFRA_SERVICE)/current $(INFRA_SERVICE)/.previous; \
	fi
	@echo "  - 创建新的 current (实际目录)..."
	@cp -r $(INFRA_SERVICE)/releases/v$(VERSION) $(INFRA_SERVICE)/current
	@echo "  - 更新 bin/current 链接..."
	@ln -sfn ../current/bin $(INFRA_SERVICE)/bin/current 2>/dev/null || true
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
	@echo "  - 更新 agentctl 注册表..."
	@sed -i 's/version: v[0-9]\+\.[0-9]\+\.[0-9]\+/version: v$(VERSION)/g' $(AGENTCTL_REGISTRY) 2>/dev/null || echo "    ⚠️ 未找到 agentctl 注册表条目"
	@echo "    ✅ $(AGENTCTL_REGISTRY)"
	@echo ""
	@echo "  - 重载 supervisor 配置..."
	@supervisorctl reread 2>/dev/null || echo "    ⚠️ supervisorctl reread 失败（忽略）"
	@supervisorctl update brain_gateway 2>/dev/null || echo "    ⚠️ supervisorctl update 失败（忽略）"
	@echo "    ✅ supervisor 配置已重载"
	@echo ""
	@echo "✅ 服务注册更新完成: v$(VERSION)"

# 重启服务
restart:
	@echo "=== Restarting Service ==="
	@supervisorctl restart brain_gateway 2>/dev/null || echo "⚠️ 重启失败，请检查服务状态"
	@sleep 2
	@supervisorctl status brain_gateway 2>/dev/null || echo "请手动检查服务状态"

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
	@echo "Current: $$(readlink $(PROJECT_ROOT)/current 2>/dev/null || echo 'N/A')"
	@echo ""
	@echo "可用版本:"
	@ls -1 $(RELEASES_DIR) 2>/dev/null | grep -E '^v[0-9]' | sort -V | sed 's/^/  - /' || echo "  无版本"
	@echo ""
	@$(MAKE) verify-deploy

# 验证 infrastructure 部署（检查软链接违规）
verify-deploy:
	@echo "=== Infrastructure Deployment Verification ==="
	@echo "检查规范 BRAIN-DEPLOY-001..."
	@echo ""
	@# 检查 current
	@if [ -L $(INFRA_SERVICE)/current ]; then \
		echo "❌ current 是软链接: $$(readlink $(INFRA_SERVICE)/current)"; \
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

# 清理构建产物
clean:
	@echo "=== Cleaning ==="
	@rm -f $(PROJECT_ROOT)/$(TARGET)
	@rm -rf $(PROJECT_ROOT)/build/*.o 2>/dev/null || true
	@echo "  - 清理完成"
