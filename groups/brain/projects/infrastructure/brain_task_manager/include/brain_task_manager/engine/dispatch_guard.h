#pragma once
#include "brain_task_manager/core/types.h"
#include "brain_task_manager/core/logger.h"
#include <string>
#include <unordered_map>
#include <vector>
#include <mutex>

// 每个 project 的 dispatch gate 状态
struct GuardState {
  bool stats_checked           = false;
  int  stats_checked_task_count = 0;
  bool pipeline_valid          = false;
  bool deps_set                = false;
  std::string updated_at;
};

struct GuardCheckResult {
  bool pass = false;
  std::vector<std::string> missing;
};

// DispatchGuard: 防止 task 在 project 未经检查前被派发
// 存储路径: {data_dir}/dispatch_guard.json（全局单文件，按 project_id 索引）
class DispatchGuard {
public:
  explicit DispatchGuard(const std::string& data_dir);

  int  Load();
  bool Save();

  void MarkStatsChecked(const std::string& project_id, int task_count);
  void MarkPipelineValid(const std::string& project_id, bool valid);
  void MarkDepsSet(const std::string& project_id);

  GuardCheckResult Check(const std::string& project_id) const;
  GuardState       GetState(const std::string& project_id) const;

private:
  std::string data_dir_;
  std::string file_path_;
  mutable std::mutex mu_;
  std::unordered_map<std::string, GuardState> states_;  // project_id → GuardState
};
