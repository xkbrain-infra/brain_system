#pragma once
#include <cstdint>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

struct KeywordRule {
  std::string pattern;
  std::string target;
};

struct RoutingConfig {
  std::unordered_map<std::string, std::string> platforms;    // platform -> agent
  std::unordered_map<std::string, std::string> chat_types;  // chat_type -> agent
  std::vector<KeywordRule> keywords;
  std::string default_target;
  std::unordered_map<std::string, std::string> reply_targets;     // platform -> service
  std::unordered_map<std::string, std::string> bot_service_map;   // bot_name -> service
};

struct IpcConfig {
  std::string socket_path = "/tmp/brain_ipc.sock";
  uint32_t poll_interval_ms = 100;
  uint32_t heartbeat_interval_s = 10;
  uint32_t reconnect_interval_s = 5;
  int32_t max_retries = -1;  // -1 = unlimited
};

struct ServiceConfig {
  std::string name = "service-brain_gateway";
  std::string host = "0.0.0.0";
  uint16_t port = 8200;
  std::string log_level = "INFO";
};

struct PermissionEntry {
  std::vector<std::string> allowed_users;  // empty = allow all
};

struct RateLimitConfig {
  uint32_t tokens_per_minute = 10;
};

struct StatsConfig {
  bool enabled = true;
  uint32_t flush_interval_s = 60;
};

struct ClusterConfig {
  bool enabled = false;
  std::string node_id;
};

struct AppConfig {
  ServiceConfig service;
  IpcConfig ipc;
  RoutingConfig routing;
  std::unordered_map<std::string, PermissionEntry> permissions;  // platform -> entry
  RateLimitConfig rate_limit;
  StatsConfig stats;
  ClusterConfig cluster;
};

// Returns nullopt on error (logs reason to stderr)
std::optional<AppConfig> LoadConfig(const std::string& path);
