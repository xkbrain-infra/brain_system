# brain-google-api Makefile
CC = gcc
CFLAGS = -Wall -Wextra -O2 -pthread -D_GNU_SOURCE \
	-I$(SRC_DIR)/app \
	-I$(SRC_DIR)/core \
	-I$(SRC_DIR)/domain \
	-I$(SRC_DIR)/infra \
	-I$(SRC_DIR)/protocol \
	-I$(SRC_DIR)/shared
LDFLAGS = -lcurl -ljansson -lssl -lcrypto -lpthread

TARGET = brain_google_api
VERSION = v0.1.0

SRC_DIR = src
BUILD_DIR = build
RELEASE_DIR = releases/$(VERSION)
RELEASE_BIN_DIR = $(RELEASE_DIR)/bin
BIN_DIR = bin

SRCS = \
	$(SRC_DIR)/app/main.c \
	$(SRC_DIR)/core/logger.c \
	$(SRC_DIR)/core/config.c \
	$(SRC_DIR)/domain/account_mgr.c \
	$(SRC_DIR)/domain/acl.c \
	$(SRC_DIR)/infra/google/google_core.c \
	$(SRC_DIR)/infra/google/google_gmail.c \
	$(SRC_DIR)/infra/google/google_drive.c \
	$(SRC_DIR)/infra/google/google_calendar.c \
	$(SRC_DIR)/infra/google/google_docs_slides.c \
	$(SRC_DIR)/infra/google/google_tasks.c \
	$(SRC_DIR)/infra/google/google_people.c \
	$(SRC_DIR)/infra/google/google_sheets.c \
	$(SRC_DIR)/infra/oauth2.c \
	$(SRC_DIR)/infra/ipc_client.c \
	$(SRC_DIR)/protocol/mcp_protocol.c \
	$(SRC_DIR)/protocol/google_api_tool.c \
	$(SRC_DIR)/shared/base64.c \
	$(SRC_DIR)/shared/crypto.c
OBJS = $(patsubst $(SRC_DIR)/%.c,$(BUILD_DIR)/%.o,$(SRCS))
TARGET_PATH = $(RELEASE_BIN_DIR)/$(TARGET)

.PHONY: all clean link-current

all: $(TARGET_PATH) link-current

$(TARGET_PATH): $(OBJS) | $(RELEASE_BIN_DIR)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

$(BUILD_DIR)/%.o: $(SRC_DIR)/%.c | $(BUILD_DIR)
	mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c -o $@ $<

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(RELEASE_BIN_DIR):
	mkdir -p $(RELEASE_BIN_DIR)

link-current: $(TARGET_PATH) | $(BIN_DIR)
	ln -sfn ../$(RELEASE_BIN_DIR) $(BIN_DIR)/current

$(BIN_DIR):
	mkdir -p $(BIN_DIR)

clean:
	rm -rf $(BUILD_DIR) $(TARGET_PATH)
