#include <gtest/gtest.h>
#include "traffic_stats.h"
#include <thread>
#include <vector>

// T-STAT-001: 并发计数正确性
TEST(TrafficStatsTest, ConcurrentRecordIsCorrect) {
  TrafficStats stats;
  constexpr int kThreads = 10;
  constexpr int kPerThread = 100;

  std::vector<std::thread> threads;
  threads.reserve(kThreads);
  for (int i = 0; i < kThreads; ++i) {
    threads.emplace_back([&] {
      for (int j = 0; j < kPerThread; ++j) {
        stats.RecordMessage("telegram", "inbound");
      }
    });
  }
  for (auto& t : threads) t.join();

  auto summary = stats.GetSummary();
  EXPECT_EQ(summary["total_messages"].get<uint64_t>(), kThreads * kPerThread);
  EXPECT_EQ(summary["by_platform"]["telegram"]["inbound"].get<uint64_t>(),
            kThreads * kPerThread);
}

// T-STAT-002: get_summary 返回合法 JSON 且包含必填字段
TEST(TrafficStatsTest, GetSummaryHasRequiredFields) {
  TrafficStats stats;
  stats.RecordMessage("telegram", "inbound");
  stats.RecordRoute("agent_system_frontdesk");
  stats.RecordError("telegram");

  auto summary = stats.GetSummary();
  // Must be parseable (it is since we constructed it as json object)
  EXPECT_TRUE(summary.is_object());
  EXPECT_TRUE(summary.contains("total_messages"));
  EXPECT_TRUE(summary.contains("total_errors"));
  EXPECT_TRUE(summary.contains("by_direction"));
  EXPECT_TRUE(summary.contains("by_platform"));
  EXPECT_TRUE(summary.contains("by_agent"));

  // Verify re-serializable
  std::string serialized = summary.dump();
  auto reparsed = nlohmann::json::parse(serialized);
  EXPECT_EQ(reparsed["total_messages"].get<uint64_t>(), 1u);
  EXPECT_EQ(reparsed["total_errors"].get<uint64_t>(), 1u);
}

// Additional: error counting
TEST(TrafficStatsTest, ErrorCountingWorks) {
  TrafficStats stats;
  stats.RecordError("telegram");
  stats.RecordError("telegram");
  auto s = stats.GetSummary();
  EXPECT_EQ(s["total_errors"].get<uint64_t>(), 2u);
  EXPECT_EQ(s["by_platform"]["telegram"]["errors"].get<uint64_t>(), 2u);
}
