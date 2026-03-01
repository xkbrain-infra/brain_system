# brain_gateway - C++20 unified gateway service
CXX = g++
CXXFLAGS = -std=c++20 -fPIC -fno-exceptions -DNO_STD_MUTEX \
           -Wall -Wextra -O2 -pthread \
           -I$(SRC_DIR) -isystem $(INCLUDE_DIR)
LDFLAGS = -pthread

TARGET = brain_gateway
VERSION ?= v0.1.0

SRC_DIR     = src
INCLUDE_DIR = include
BUILD_DIR   = build
RELEASE_DIR = releases/$(VERSION)
RELEASE_BIN = $(RELEASE_DIR)/bin
BIN_DIR     = bin
TESTS_DIR   = tests

SRCS = $(SRC_DIR)/main.cpp \
       $(SRC_DIR)/config.cpp \
       $(SRC_DIR)/traffic_stats.cpp \
       $(SRC_DIR)/permission.cpp \
       $(SRC_DIR)/rate_limiter.cpp \
       $(SRC_DIR)/router.cpp \
       $(SRC_DIR)/ipc_bridge.cpp \
       $(SRC_DIR)/http_server.cpp \
       $(SRC_DIR)/gateway.cpp \
       $(SRC_DIR)/hot_reload.cpp

OBJS = $(patsubst $(SRC_DIR)/%.cpp,$(BUILD_DIR)/%.o,$(SRCS))
TARGET_PATH = $(RELEASE_BIN)/$(TARGET)

# Conan-generated toolchain (installed by 'make conan-install')
-include $(BUILD_DIR)/conanbuildinfo.mak

.PHONY: all clean link-current test fmt-check conan-install install-deps

all: $(TARGET_PATH) link-current

$(TARGET_PATH): $(OBJS) | $(RELEASE_BIN)
	$(CXX) $(CXXFLAGS) -o $@ $^ $(LDFLAGS) $(CONAN_LIBS) $(CONAN_LIB_DIRS:%=-L%)

$(BUILD_DIR)/%.o: $(SRC_DIR)/%.cpp | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $(CONAN_INCLUDE_DIRS:%=-I%) -c -o $@ $<

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(RELEASE_BIN):
	mkdir -p $(RELEASE_BIN)

link-current: $(TARGET_PATH) | $(BIN_DIR)
	ln -sfn ../$(RELEASE_BIN) $(BIN_DIR)/current

$(BIN_DIR):
	mkdir -p $(BIN_DIR)

clean:
	rm -f $(BUILD_DIR)/*.o $(TARGET_PATH)

# Install gtest system package (fallback if conan unavailable)
install-deps:
	apt-get install -y libgtest-dev 2>/dev/null || \
	pip3 install conan && $(MAKE) conan-install

# Conan dependency installation (gtest/1.14.0)
conan-install: | $(BUILD_DIR)
	conan install . --output-folder=$(BUILD_DIR) --build=missing -s build_type=Release

# Unit tests
TEST_SRCS = $(TESTS_DIR)/test_router.cpp $(TESTS_DIR)/test_stats.cpp
TEST_OBJS = $(patsubst $(TESTS_DIR)/%.cpp,$(BUILD_DIR)/%.o,$(TEST_SRCS))
CORE_OBJS = $(filter-out $(BUILD_DIR)/main.o,$(OBJS))

test: $(CORE_OBJS) $(TEST_OBJS)
	$(CXX) $(CXXFLAGS) -o $(BUILD_DIR)/run_tests $^ $(LDFLAGS) \
	  $(CONAN_LIBS) $(CONAN_LIB_DIRS:%=-L%) -lgtest -lgtest_main
	$(BUILD_DIR)/run_tests

$(BUILD_DIR)/test_%.o: $(TESTS_DIR)/test_%.cpp | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $(CONAN_INCLUDE_DIRS:%=-I%) -c -o $@ $<

fmt-check:
	@if command -v clang-format >/dev/null 2>&1; then \
	  find $(SRC_DIR) $(TESTS_DIR) -name '*.cpp' -o -name '*.h' | \
	    xargs clang-format --dry-run --Werror 2>&1 && echo "fmt OK"; \
	else \
	  echo "clang-format not found, skipping"; \
	fi
