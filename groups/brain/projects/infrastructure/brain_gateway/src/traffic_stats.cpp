#include "traffic_stats.h"

void TrafficStats::RecordMessage(const std::string& platform, const std::string& direction) {
  total_messages_.fetch_add(1, std::memory_order_relaxed);
  if (direction == "inbound") {
    inbound_.fetch_add(1, std::memory_order_relaxed);
  } else {
    outbound_.fetch_add(1, std::memory_order_relaxed);
  }

  SpinlockGuard g(map_lock_);
  auto& ps = by_platform_[platform];
  if (direction == "inbound") {
    ++ps.inbound;
  } else {
    ++ps.outbound;
  }
}

void TrafficStats::RecordRoute(const std::string& agent) {
  SpinlockGuard g(map_lock_);
  ++by_agent_[agent].routed;
}

void TrafficStats::RecordError(const std::string& platform) {
  total_errors_.fetch_add(1, std::memory_order_relaxed);
  SpinlockGuard g(map_lock_);
  ++by_platform_[platform].errors;
}

nlohmann::json TrafficStats::GetSummary() const {
  // Snapshot maps under lock, then build JSON without lock
  std::unordered_map<std::string, PlatformStat> plat_snap;
  std::unordered_map<std::string, AgentStat> agent_snap;
  {
    SpinlockGuard g(map_lock_);
    plat_snap  = by_platform_;
    agent_snap = by_agent_;
  }

  nlohmann::json j;
  j["total_messages"] = total_messages_.load(std::memory_order_relaxed);
  j["total_errors"]   = total_errors_.load(std::memory_order_relaxed);
  j["by_direction"]   = {
    {"inbound",  inbound_.load(std::memory_order_relaxed)},
    {"outbound", outbound_.load(std::memory_order_relaxed)}
  };

  nlohmann::json plat_j = nlohmann::json::object();
  for (auto& [name, ps] : plat_snap) {
    plat_j[name] = {
      {"inbound",  ps.inbound},
      {"outbound", ps.outbound},
      {"errors",   ps.errors}
    };
  }
  j["by_platform"] = plat_j;

  nlohmann::json agent_j = nlohmann::json::object();
  for (auto& [name, as] : agent_snap) {
    agent_j[name] = {{"routed", as.routed}, {"errors", as.errors}};
  }
  j["by_agent"] = agent_j;

  return j;
}
