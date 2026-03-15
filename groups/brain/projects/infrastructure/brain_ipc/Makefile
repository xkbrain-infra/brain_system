# Brain IPC 构建与发布系统
# 规范: /xkagent_infra/groups/brain/spec/deployment/release_process.yaml

PROJECT_NAME := brain_ipc
PROJECT_ROOT := /xkagent_infra/groups/brain/projects/infrastructure/$(PROJECT_NAME)
INFRA_SERVICE := /xkagent_infra/brain/infrastructure/service/$(PROJECT_NAME)
RELEASES_DIR := $(PROJECT_ROOT)/releases

CC := gcc
CFLAGS := -Wall -g -O2 -D_GNU_SOURCE
LDFLAGS := -lpthread -lrt -ljansson -lcrypto -lssl

SRCS := $(wildcard $(PROJECT_ROOT)/src/*.c)
TARGET := brain_ipc

.PHONY: all help build clean release deploy verify

all: help

help:
	@echo "Brain IPC Build System"
	@echo "======================"
	@echo ""
	@echo "可用目标:"
	@echo "  make build       - 编译 brain_ipc"
	@echo "  make release     - 创建版本 (VERSION=x.y.z)"
	@echo "  make deploy      - 部署到 infrastructure"
	@echo "  make verify      - 验证部署"
	@echo ""

build:
	@echo "=== Building $(PROJECT_NAME) ==="
	@cd $(PROJECT_ROOT)/src && \
		$(CC) $(CFLAGS) -o $(TARGET) *.c $(LDFLAGS) && \
		echo "✅ 编译完成: $(TARGET)"

release:
	@if [ -z "$(VERSION)" ]; then \
		echo "错误: 请指定 VERSION 参数"; \
		exit 1; \
	fi
	@echo "=== Releasing $(PROJECT_NAME) v$(VERSION) ==="
	@mkdir -p $(RELEASES_DIR)/v$(VERSION)
	@cp -r $(PROJECT_ROOT)/src/* $(RELEASES_DIR)/v$(VERSION)/
	@echo "✅ 版本创建完成: v$(VERSION)"

deploy:
	@if [ -z "$(VERSION)" ]; then \
		echo "错误: 请指定 VERSION 参数"; \
		exit 1; \
	fi
	@echo "=== Deploying $(PROJECT_NAME) v$(VERSION) ==="
	@mkdir -p $(INFRA_SERVICE)/releases/v$(VERSION)
	@cp -r $(RELEASES_DIR)/v$(VERSION)/* $(INFRA_SERVICE)/releases/v$(VERSION)/
	@mkdir -p $(INFRA_SERVICE)/bin
	@cp $(INFRA_SERVICE)/releases/v$(VERSION)/brain_ipc $(INFRA_SERVICE)/bin/ 2>/dev/null || true
	@echo "✅ 部署完成: v$(VERSION)"

verify:
	@echo "=== Verification ==="
	@ls -la $(RELEASES_DIR)/ 2>/dev/null | grep v || echo "无版本"

clean:
	@rm -f $(PROJECT_ROOT)/src/brain_ipc
