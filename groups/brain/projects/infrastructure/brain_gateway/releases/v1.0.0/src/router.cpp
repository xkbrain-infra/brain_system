#include "router.h"
#include "logger.h"

Router::Router(const RoutingConfig& cfg) : config_(&cfg) {
  CompileRules();
  LOG_INFO("router", LogFmt("initialized: %zu keyword rules, %zu platform routes",
                             keyword_rules_.size(), cfg.platforms.size()));
}

Router::~Router() = default;

Router::Router(Router&& other) noexcept
    : config_(other.config_),
      keyword_rules_(std::move(other.keyword_rules_)) {
  other.config_ = nullptr;
}

Router& Router::operator=(Router&& other) noexcept {
  if (this != &other) {
    config_ = other.config_;
    keyword_rules_ = std::move(other.keyword_rules_);
    other.config_ = nullptr;
  }
  return *this;
}

void Router::ReloadConfig(const RoutingConfig& cfg) {
  config_ = &cfg;
  CompileRules();
  LOG_INFO("router", LogFmt("reloaded: %zu keyword rules, %zu platform routes",
                             keyword_rules_.size(), cfg.platforms.size()));
}

void Router::CompileRules() {
  keyword_rules_.clear();
  if (!config_) return;

  for (const auto& kw : config_->keywords) {
    // Strip (?i) inline flag prefix if present (icase is already set via std::regex::icase)
    std::string pat = kw.pattern;
    if (pat.rfind("(?i)", 0) == 0) pat = pat.substr(4);
    // With -fno-exceptions: invalid regex aborts at startup (config error)
    keyword_rules_.push_back({std::regex(pat, std::regex::icase), kw.target});
  }
}

RouteResult Router::RouteIncoming(const IncomingMsg& msg) const {
  // Priority: keyword > chat_type > platform > default
  for (const auto& rule : keyword_rules_) {
    if (std::regex_search(msg.content, rule.regex)) {
      LOG_INFO("router", LogFmt("keyword match -> %s", rule.target.c_str()));
      return {rule.target, "keyword", "inbound"};
    }
  }

  if (!msg.chat_type.empty()) {
    auto it = config_->chat_types.find(msg.chat_type);
    if (it != config_->chat_types.end()) {
      LOG_INFO("router", LogFmt("chat_type '%s' -> %s", msg.chat_type.c_str(), it->second.c_str()));
      return {it->second, "chat_type", "inbound"};
    }
  }

  {
    auto it = config_->platforms.find(msg.platform);
    if (it != config_->platforms.end()) {
      LOG_INFO("router", LogFmt("platform '%s' -> %s", msg.platform.c_str(), it->second.c_str()));
      return {it->second, "platform", "inbound"};
    }
  }

  LOG_INFO("router", LogFmt("default -> %s", config_->default_target.c_str()));
  return {config_->default_target, "default", "inbound"};
}

RouteResult Router::RouteReply(const ReplyMsg& msg) const {
  const std::string& platform = msg.reply_to_platform;

  // target_bot routing for telegram
  if (!msg.target_bot.empty() && platform == "telegram") {
    auto it = config_->bot_service_map.find(msg.target_bot);
    if (it != config_->bot_service_map.end()) {
      return {it->second, "reply", "outbound"};
    }
  }

  auto it = config_->reply_targets.find(platform);
  if (it != config_->reply_targets.end()) {
    return {it->second, "reply", "outbound"};
  }

  LOG_WARN("router", LogFmt("unknown reply platform '%s'", platform.c_str()));
  return {"", "reply", "outbound"};
}

bool Router::IsIncoming(const std::string& from) {
  // from field starts with "service-" and contains "_api"
  return from.rfind("service-", 0) == 0 && from.find("_api") != std::string::npos;
}

bool Router::IsReply(const std::string& from) {
  return from.rfind("agent_", 0) == 0 || from.rfind("agent-", 0) == 0;
}
