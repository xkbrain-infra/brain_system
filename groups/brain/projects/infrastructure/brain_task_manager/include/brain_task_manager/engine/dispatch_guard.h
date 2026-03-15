#pragma once
#include "brain_task_manager/core/types.h"
#include "brain_task_manager/core/logger.h"
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <mutex>

// Per-spec dispatch guard state
struct GuardState {
  bool stats_checked = false;
  int  stats_checked_task_count = 0;
  bool pipeline_valid = false;
  bool deps_set = false;
  std::string updated_at;
};

struct GuardCheckResult {
  bool pass = false;
  std::vector<std::string> missing;  // list of unmet conditions
};

class DispatchGuard {
public:
  explicit DispatchGuard(const std::string& data_dir);

  // Load guard state from JSON file.
  int Load();

  // Save guard state to JSON file (atomic write).
  bool Save();

  // Mark stats_checked for a spec.
  void MarkStatsChecked(const std::string& spec_id, int task_count);

  // Mark pipeline_valid for a spec.
  void MarkPipelineValid(const std::string& spec_id, bool valid);

  // Mark deps_set for a spec.
  void MarkDepsSet(const std::string& spec_id);

  // Check if all three gates pass for a spec.
  GuardCheckResult Check(const std::string& spec_id) const;

  // Get guard state for a spec (for reporting).
  GuardState GetState(const std::string& spec_id) const;

private:
  std::string data_dir_;
  std::string file_path_;
  mutable std::mutex mu_;
  std::unordered_map<std::string, GuardState> states_;
};
