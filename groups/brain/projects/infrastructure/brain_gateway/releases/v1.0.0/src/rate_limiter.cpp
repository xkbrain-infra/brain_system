#include "rate_limiter.h"
#include "logger.h"

bool RateLimiter::Allow(const std::string& user_id) {
  auto now = clock_();
  SpinlockGuard g(lock_);
  auto it = buckets_.find(user_id);
  if (it == buckets_.end()) {
    auto [ins, ok] = buckets_.emplace(user_id, TokenBucket(tokens_per_minute_, now));
    (void)ok;
    it = ins;
  }
  bool allowed = it->second.TryConsume(now);
  if (!allowed) {
    LOG_WARN("rate_limiter", LogFmt("rate limited user: %s", user_id.c_str()));
  }
  return allowed;
}
