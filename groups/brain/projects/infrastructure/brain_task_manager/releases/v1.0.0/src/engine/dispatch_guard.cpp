#include "brain_task_manager/engine/dispatch_guard.h"
#include <fstream>

DispatchGuard::DispatchGuard(const std::string& data_dir) : data_dir_(data_dir) {
  if (!data_dir_.empty() && data_dir_.back() != '/') data_dir_ += '/';
  file_path_ = data_dir_ + "project_dispatch_guard.json";
}

int DispatchGuard::Load() {
  std::lock_guard<std::mutex> lock(mu_);
  std::ifstream f(file_path_);
  if (!f.is_open()) {
    LOG_WARN("dispatch_guard", LogFmt("guard file not found: %s, starting empty", file_path_.c_str()));
    return 0;
  }

  auto j = json::parse(f, nullptr, false);
  if (j.is_discarded() || !j.contains("guards") || !j["guards"].is_object()) {
    LOG_ERROR("dispatch_guard", LogFmt("failed to parse guard file: %s", file_path_.c_str()));
    return 0;
  }

  states_.clear();
  for (auto& [key, val] : j["guards"].items()) {
    GuardState gs;
    gs.stats_checked = val.value("stats_checked", false);
    gs.stats_checked_task_count = val.value("stats_checked_task_count", 0);
    gs.pipeline_valid = val.value("pipeline_valid", false);
    gs.deps_set = val.value("deps_set", false);
    gs.updated_at = val.value("updated_at", "");
    states_[key] = gs;
  }

  LOG_INFO("dispatch_guard", LogFmt("loaded %d guard states from %s", (int)states_.size(), file_path_.c_str()));
  return static_cast<int>(states_.size());
}

bool DispatchGuard::Save() {
  std::lock_guard<std::mutex> lock(mu_);

  json j;
  j["guards"] = json::object();
  for (auto& [id, gs] : states_) {
    j["guards"][id] = {
      {"stats_checked", gs.stats_checked},
      {"stats_checked_task_count", gs.stats_checked_task_count},
      {"pipeline_valid", gs.pipeline_valid},
      {"deps_set", gs.deps_set},
      {"updated_at", gs.updated_at}
    };
  }

  std::string tmp_path = file_path_ + ".tmp";
  {
    std::ofstream out(tmp_path);
    if (!out.is_open()) {
      LOG_ERROR("dispatch_guard", LogFmt("failed to open tmp file: %s", tmp_path.c_str()));
      return false;
    }
    out << j.dump(2) << "\n";
    out.flush();
    if (!out.good()) {
      LOG_ERROR("dispatch_guard", LogFmt("write failed: %s", tmp_path.c_str()));
      return false;
    }
  }

  if (rename(tmp_path.c_str(), file_path_.c_str()) != 0) {
    LOG_ERROR("dispatch_guard", LogFmt("rename failed: %s -> %s", tmp_path.c_str(), file_path_.c_str()));
    return false;
  }

  return true;
}

void DispatchGuard::MarkStatsChecked(const std::string& spec_id, int task_count) {
  std::lock_guard<std::mutex> lock(mu_);
  states_[spec_id].stats_checked = true;
  states_[spec_id].stats_checked_task_count = task_count;
  states_[spec_id].updated_at = NowUTC();
}

void DispatchGuard::MarkPipelineValid(const std::string& spec_id, bool valid) {
  std::lock_guard<std::mutex> lock(mu_);
  states_[spec_id].pipeline_valid = valid;
  states_[spec_id].updated_at = NowUTC();
}

void DispatchGuard::MarkDepsSet(const std::string& spec_id) {
  std::lock_guard<std::mutex> lock(mu_);
  states_[spec_id].deps_set = true;
  states_[spec_id].updated_at = NowUTC();
}

GuardCheckResult DispatchGuard::Check(const std::string& spec_id) const {
  std::lock_guard<std::mutex> lock(mu_);
  GuardCheckResult result;

  auto it = states_.find(spec_id);
  if (it == states_.end()) {
    result.pass = false;
    result.missing.push_back("TASK_STATS not executed for " + spec_id);
    result.missing.push_back("TASK_PIPELINE_CHECK not executed for " + spec_id);
    result.missing.push_back("PROJECT_DEPENDENCY_SET not executed for " + spec_id);
    return result;
  }

  const GuardState& gs = it->second;

  if (!gs.stats_checked) {
    result.missing.push_back("TASK_STATS not executed for " + spec_id);
  }
  if (!gs.pipeline_valid) {
    result.missing.push_back("TASK_PIPELINE_CHECK not passed for " + spec_id);
  }
  if (!gs.deps_set) {
    result.missing.push_back("PROJECT_DEPENDENCY_SET not executed for " + spec_id);
  }

  result.pass = result.missing.empty();
  return result;
}

GuardState DispatchGuard::GetState(const std::string& spec_id) const {
  std::lock_guard<std::mutex> lock(mu_);
  auto it = states_.find(spec_id);
  if (it == states_.end()) return GuardState{};
  return it->second;
}
