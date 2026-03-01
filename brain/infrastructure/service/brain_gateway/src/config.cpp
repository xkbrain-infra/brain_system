#include "config.h"
#include "logger.h"

#include <fstream>
#include <json.hpp>

using json = nlohmann::json;

static RoutingConfig ParseRouting(const json& j) {
  RoutingConfig rc;
  if (j.contains("platforms") && j["platforms"].is_object()) {
    for (auto& [k, v] : j["platforms"].items()) {
      rc.platforms[k] = v.get<std::string>();
    }
  }
  if (j.contains("chat_types") && j["chat_types"].is_object()) {
    for (auto& [k, v] : j["chat_types"].items()) {
      rc.chat_types[k] = v.get<std::string>();
    }
  }
  if (j.contains("keywords") && j["keywords"].is_array()) {
    for (auto& kw : j["keywords"]) {
      KeywordRule rule;
      rule.pattern = kw.value("pattern", "");
      rule.target  = kw.value("target", "");
      if (!rule.pattern.empty() && !rule.target.empty()) {
        rc.keywords.push_back(std::move(rule));
      }
    }
  }
  rc.default_target = j.value("default", "agent_system_frontdesk");
  if (j.contains("reply_targets") && j["reply_targets"].is_object()) {
    for (auto& [k, v] : j["reply_targets"].items()) {
      rc.reply_targets[k] = v.get<std::string>();
    }
  }
  if (j.contains("bot_service_map") && j["bot_service_map"].is_object()) {
    for (auto& [k, v] : j["bot_service_map"].items()) {
      rc.bot_service_map[k] = v.get<std::string>();
    }
  }
  return rc;
}

std::optional<AppConfig> LoadConfig(const std::string& path) {
  std::ifstream f(path);
  if (!f.is_open()) {
    LOG_ERROR("config", LogFmt("Failed to open config file: %s", path.c_str()));
    return std::nullopt;
  }

  // Use non-throwing parse (returns discarded value on error)
  json j = json::parse(f, nullptr, /*allow_exceptions=*/false);
  if (j.is_discarded()) {
    LOG_ERROR("config", "Failed to parse config: invalid JSON");
    return std::nullopt;
  }

  AppConfig cfg;

  if (j.contains("service")) {
    auto& s = j["service"];
    cfg.service.name      = s.value("name", cfg.service.name);
    cfg.service.host      = s.value("host", cfg.service.host);
    cfg.service.port      = s.value("port", cfg.service.port);
    cfg.service.log_level = s.value("log_level", cfg.service.log_level);
  }

  if (j.contains("ipc")) {
    auto& i = j["ipc"];
    cfg.ipc.socket_path        = i.value("socket_path", cfg.ipc.socket_path);
    cfg.ipc.poll_interval_ms   = i.value("poll_interval_ms", cfg.ipc.poll_interval_ms);
    cfg.ipc.heartbeat_interval_s = i.value("heartbeat_interval_s", cfg.ipc.heartbeat_interval_s);
    cfg.ipc.reconnect_interval_s = i.value("reconnect_interval_s", cfg.ipc.reconnect_interval_s);
    cfg.ipc.max_retries        = i.value("max_retries", cfg.ipc.max_retries);
  }

  if (j.contains("routing")) {
    cfg.routing = ParseRouting(j["routing"]);
  }

  if (j.contains("permissions") && j["permissions"].is_object()) {
    for (auto& [platform, rules] : j["permissions"].items()) {
      PermissionEntry entry;
      if (rules.contains("allowed_users") && rules["allowed_users"].is_array()) {
        for (auto& u : rules["allowed_users"]) {
          entry.allowed_users.push_back(u.get<std::string>());
        }
      }
      cfg.permissions[platform] = std::move(entry);
    }
  }

  if (j.contains("rate_limit")) {
    cfg.rate_limit.tokens_per_minute =
        j["rate_limit"].value("tokens_per_minute", cfg.rate_limit.tokens_per_minute);
  }

  if (j.contains("stats")) {
    cfg.stats.enabled          = j["stats"].value("enabled", cfg.stats.enabled);
    cfg.stats.flush_interval_s = j["stats"].value("flush_interval_s", cfg.stats.flush_interval_s);
  }

  if (j.contains("cluster")) {
    cfg.cluster.enabled = j["cluster"].value("enabled", cfg.cluster.enabled);
    cfg.cluster.node_id = j["cluster"].value("node_id", cfg.cluster.node_id);
  }

  return cfg;
}
