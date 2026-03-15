#pragma once
// Traffic statistics with atomic_flag spinlock (NO_STD_MUTEX compliant)

#include <atomic>
#include <cstdint>
#include <string>
#include <unordered_map>
#include <json.hpp>

// Spinlock using std::atomic_flag (C++20 guaranteed lock-free)
struct Spinlock {
  std::atomic_flag flag_ = ATOMIC_FLAG_INIT;
  void Lock() noexcept {
    while (flag_.test_and_set(std::memory_order_acquire)) {
      // Busy-wait; for short critical sections this is acceptable
    }
  }
  void Unlock() noexcept { flag_.clear(std::memory_order_release); }
};

struct SpinlockGuard {
  Spinlock& sl_;
  explicit SpinlockGuard(Spinlock& sl) : sl_(sl) { sl_.Lock(); }
  ~SpinlockGuard() { sl_.Unlock(); }
};

struct PlatformStat {
  uint64_t inbound = 0;
  uint64_t outbound = 0;
  uint64_t errors = 0;
};

struct AgentStat {
  uint64_t routed = 0;
  uint64_t errors = 0;
};

class TrafficStats {
 public:
  void RecordMessage(const std::string& platform, const std::string& direction);
  void RecordRoute(const std::string& agent);
  void RecordError(const std::string& platform);
  nlohmann::json GetSummary() const;

 private:
  std::atomic<uint64_t> total_messages_{0};
  std::atomic<uint64_t> total_errors_{0};
  std::atomic<uint64_t> inbound_{0};
  std::atomic<uint64_t> outbound_{0};

  mutable Spinlock map_lock_;
  std::unordered_map<std::string, PlatformStat> by_platform_;
  std::unordered_map<std::string, AgentStat> by_agent_;
};
