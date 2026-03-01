#pragma once
#include "config.h"
#include <optional>
#include <regex>
#include <string>
#include <vector>

struct RouteResult {
  std::string target;
  std::string rule_matched;  // "keyword" | "chat_type" | "platform" | "default" | "reply"
  std::string direction;     // "inbound" | "outbound"
};

struct IncomingMsg {
  std::string platform;
  std::string content;
  std::string chat_type;  // from metadata
  std::string from;       // sender service name
};

struct ReplyMsg {
  std::string from;              // agent name
  std::string reply_to_platform;
  std::string target_bot;       // optional
};

class Router {
 public:
  explicit Router(const RoutingConfig& cfg);
  ~Router();

  // Non-copyable
  Router(const Router&) = delete;
  Router& operator=(const Router&) = delete;

  // Movable
  Router(Router&& other) noexcept;
  Router& operator=(Router&& other) noexcept;

  // Reload configuration (for hot reload)
  void ReloadConfig(const RoutingConfig& cfg);

  RouteResult RouteIncoming(const IncomingMsg& msg) const;
  RouteResult RouteReply(const ReplyMsg& msg) const;

  // Classify message direction based on 'from' field
  static bool IsIncoming(const std::string& from);
  static bool IsReply(const std::string& from);

 private:
  const RoutingConfig* config_;

  struct CompiledRule {
    std::regex regex;
    std::string target;
  };
  std::vector<CompiledRule> keyword_rules_;

  void CompileRules();
};
