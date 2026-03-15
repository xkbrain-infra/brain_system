#pragma once
// Token bucket rate limiter with clock injection for testability
// NO_STD_MUTEX: uses atomic_flag spinlock

#include "traffic_stats.h"  // for Spinlock/SpinlockGuard

#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <string>
#include <unordered_map>

using ClockFn = std::function<std::chrono::steady_clock::time_point()>;

inline ClockFn DefaultClock() {
  return []() { return std::chrono::steady_clock::now(); };
}

struct TokenBucket {
  double tokens;
  std::chrono::steady_clock::time_point last_update;
  double rate_per_ms;  // tokens per millisecond

  explicit TokenBucket(uint32_t tokens_per_minute,
                       std::chrono::steady_clock::time_point now)
      : tokens(static_cast<double>(tokens_per_minute)),
        last_update(now),
        rate_per_ms(static_cast<double>(tokens_per_minute) / 60000.0) {}

  // Returns true if one token was consumed, false if rate limited
  bool TryConsume(std::chrono::steady_clock::time_point now) {
    auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                          now - last_update)
                          .count();
    last_update = now;
    tokens = std::min(static_cast<double>(static_cast<uint32_t>(tokens + elapsed_ms * rate_per_ms)),
                      tokens + elapsed_ms * rate_per_ms);
    // Cap at max (tokens_per_minute = initial)
    double max_tokens = rate_per_ms * 60000.0;
    if (tokens > max_tokens) tokens = max_tokens;

    if (tokens >= 1.0) {
      tokens -= 1.0;
      return true;
    }
    return false;
  }
};

class RateLimiter {
 public:
  explicit RateLimiter(uint32_t tokens_per_minute,
                       ClockFn clock = DefaultClock())
      : tokens_per_minute_(tokens_per_minute), clock_(std::move(clock)) {}

  // Returns true if request is allowed, false if rate limited
  bool Allow(const std::string& user_id);

 private:
  uint32_t tokens_per_minute_;
  ClockFn clock_;
  mutable Spinlock lock_;
  std::unordered_map<std::string, TokenBucket> buckets_;
};
