# Service Task Manager — Build
# Dependencies: libjansson-dev, pthreads
#
# 职责：只负责 src/ → build/ 编译
# Release/版本管理：使用 scripts/release.sh

CC       = gcc
CFLAGS   = -Wall -Wextra -O2 -std=c11 -D_GNU_SOURCE
LDFLAGS  = -ljansson -lpthread

BIN_NAME = service-task_manager
SRC_DIR  = src
BUILD_DIR = build

SRCS = $(SRC_DIR)/service_task_manager.c \
       $(SRC_DIR)/task_store.c \
       $(SRC_DIR)/spec_store.c \
       $(SRC_DIR)/validator.c

OBJS = $(patsubst $(SRC_DIR)/%.c,$(BUILD_DIR)/%.o,$(SRCS))
TARGET = $(BUILD_DIR)/$(BIN_NAME)

.PHONY: all clean

all: $(TARGET)

$(BUILD_DIR)/%.o: $(SRC_DIR)/%.c $(SRC_DIR)/task_manager.h | $(BUILD_DIR)
	$(CC) $(CFLAGS) -c -o $@ $<

$(TARGET): $(OBJS) | $(BUILD_DIR)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

clean:
	rm -rf $(BUILD_DIR)
