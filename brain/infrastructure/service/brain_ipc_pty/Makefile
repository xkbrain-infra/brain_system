# Brain IPC service - structured build/release layout
CC = gcc
CFLAGS = -Wall -Wextra -O2 -pthread -D_GNU_SOURCE -I$(SRC_DIR)
LDFLAGS = -ljansson -lpthread

TARGET = brain_ipc_pty
VERSION ?= v1.0.0

SRC_DIR = src
BUILD_DIR = build
RELEASE_DIR = releases/$(VERSION)
RELEASE_BIN_DIR = $(RELEASE_DIR)/bin
BIN_DIR = bin

SRC_BASENAMES = brain_ipc msgqueue agent_registry delayed_queue conversation scheduled_queue
SRCS = $(addprefix $(SRC_DIR)/,$(addsuffix .c,$(SRC_BASENAMES)))
OBJS = $(addprefix $(BUILD_DIR)/,$(addsuffix .o,$(SRC_BASENAMES)))
TARGET_PATH = $(RELEASE_BIN_DIR)/$(TARGET)

PREFIX ?= /usr/local
SYSTEMD_DIR ?= /etc/systemd/system

.PHONY: all clean install uninstall test link-current

all: $(TARGET_PATH) link-current

$(TARGET_PATH): $(OBJS) | $(RELEASE_BIN_DIR)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

$(BUILD_DIR)/%.o: $(SRC_DIR)/%.c | $(BUILD_DIR)
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
	rm -f $(BUILD_DIR)/*.o $(TARGET_PATH)

install: all
	install -d $(PREFIX)/bin
	install -m 755 $(TARGET_PATH) $(PREFIX)/bin/$(TARGET)
	@if [ -d $(SYSTEMD_DIR) ]; then \
		install -m 644 config/brain-ipc.service $(SYSTEMD_DIR)/ 2>/dev/null || true; \
		systemctl daemon-reload 2>/dev/null || true; \
	fi

uninstall:
	rm -f $(PREFIX)/bin/$(TARGET)
	rm -f $(SYSTEMD_DIR)/brain-ipc.service
	@systemctl daemon-reload 2>/dev/null || true

test: all
	@echo "Testing brain_ipc..."
	@$(TARGET_PATH) stop 2>/dev/null || true
	@sleep 1
	@$(TARGET_PATH) &
	@sleep 1
	@echo '{"action":"ping","data":{}}' | nc -U /tmp/brain_ipc.sock
	@$(TARGET_PATH) stop
