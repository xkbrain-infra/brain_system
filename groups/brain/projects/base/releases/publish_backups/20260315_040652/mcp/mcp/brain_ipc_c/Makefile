# brain-ipc-c - C MCP server for Brain IPC
CC = gcc
CFLAGS = -Wall -Wextra -O2 -pthread -D_GNU_SOURCE
LDFLAGS = -ljansson -lpthread

# Directories
SRC_DIR = .
BUILD_DIR = build
BIN_DIR = bin

# Target
TARGET = $(BIN_DIR)/brain_ipc_c_mcp_server

# Source files
SRCS = $(SRC_DIR)/main.c $(SRC_DIR)/daemon_client.c $(SRC_DIR)/tmux_detect.c $(SRC_DIR)/notify_bridge.c $(SRC_DIR)/mcp_jsonrpc.c
OBJS = $(patsubst $(SRC_DIR)/%.c,$(BUILD_DIR)/%.o,$(SRCS))

.PHONY: all clean dirs

all: dirs $(TARGET)

dirs:
	@mkdir -p $(BUILD_DIR) $(BIN_DIR)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $@.new $^ $(LDFLAGS)
	mv -f $@.new $@

$(BUILD_DIR)/%.o: $(SRC_DIR)/%.c
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -rf $(BUILD_DIR) $(BIN_DIR)
