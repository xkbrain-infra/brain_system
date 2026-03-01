CXX      = g++
CXXFLAGS = -std=c++20 -Wall -Wextra -O2 -pthread \
           -Iinclude -isystem third_party -isystem third_party/nlohmann
LDFLAGS  = -pthread

SRC_DIR  = src
BUILD_DIR = build
BIN_DIR  = bin

VERSION  = v0.1.0
RELEASE_DIR = releases/$(VERSION)/bin

SRCS = $(shell find $(SRC_DIR) -name '*.cpp')
OBJS = $(patsubst $(SRC_DIR)/%.cpp,$(BUILD_DIR)/%.o,$(SRCS))
TARGET = $(BIN_DIR)/brain_task_manager

.PHONY: all clean release

all: $(TARGET)

$(TARGET): $(OBJS) | $(BIN_DIR)
	$(CXX) $(LDFLAGS) -o $@ $^

$(BUILD_DIR)/%.o: $(SRC_DIR)/%.cpp
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -c -o $@ $<

$(BUILD_DIR):
	mkdir -p $@

$(BIN_DIR):
	mkdir -p $@

release: $(TARGET)
	mkdir -p $(RELEASE_DIR)
	cp $(TARGET) $(RELEASE_DIR)/
	ln -sfn ../releases/$(VERSION)/bin bin/current

clean:
	rm -rf $(BUILD_DIR) $(BIN_DIR)/brain_task_manager
