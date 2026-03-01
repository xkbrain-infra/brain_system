#include "permission.h"
#include "logger.h"

bool Permission::IsAllowed(const std::string& platform, const std::string& user_id) const {
  auto it = config_.find(platform);
  if (it == config_.end()) {
    // No config for this platform: allow all
    return true;
  }
  const auto& allowed = it->second.allowed_users;
  if (allowed.empty()) {
    // Empty whitelist = allow all
    return true;
  }
  for (const auto& uid : allowed) {
    if (uid == user_id) return true;
  }
  LOG_WARN("permission", LogFmt("user %s not in %s whitelist", user_id.c_str(), platform.c_str()));
  return false;
}
