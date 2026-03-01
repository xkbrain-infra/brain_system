#pragma once
#include "config.h"
#include <string>
#include <unordered_map>

class Permission {
 public:
  explicit Permission(const std::unordered_map<std::string, PermissionEntry>& cfg)
      : config_(cfg) {}

  // Returns true if user_id is allowed on platform.
  // Empty whitelist = allow all.
  bool IsAllowed(const std::string& platform, const std::string& user_id) const;

 private:
  const std::unordered_map<std::string, PermissionEntry>& config_;
};
