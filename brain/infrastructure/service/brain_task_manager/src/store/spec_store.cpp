#include "brain_task_manager/store/spec_store.h"
#include <fstream>
#include <sys/stat.h>

SpecStore::SpecStore(const std::string& data_dir) : data_dir_(data_dir) {
  if (!data_dir_.empty() && data_dir_.back() != '/') data_dir_ += '/';
  file_path_ = data_dir_ + "specs.json";
}

int SpecStore::Load() {
  std::lock_guard<std::mutex> lock(mu_);
  std::ifstream f(file_path_);
  if (!f.is_open()) {
    LOG_WARN("spec_store", LogFmt("specs file not found: %s, starting empty", file_path_.c_str()));
    return 0;
  }

  auto j = json::parse(f, nullptr, false);
  if (j.is_discarded() || !j.contains("specs") || !j["specs"].is_object()) {
    LOG_ERROR("spec_store", LogFmt("failed to parse specs file: %s", file_path_.c_str()));
    return 0;
  }

  specs_.clear();
  for (auto& [key, val] : j["specs"].items()) {
    SpecRecord s = SpecRecord::from_json(val);
    specs_[s.spec_id] = s;
  }

  LOG_INFO("spec_store", LogFmt("loaded %d specs from %s", (int)specs_.size(), file_path_.c_str()));
  return static_cast<int>(specs_.size());
}

bool SpecStore::Save() {
  std::lock_guard<std::mutex> lock(mu_);

  json j;
  j["specs"] = json::object();
  for (auto& [id, s] : specs_) {
    j["specs"][id] = s.to_json();
  }

  std::string tmp_path = file_path_ + ".tmp";
  {
    std::ofstream out(tmp_path);
    if (!out.is_open()) {
      LOG_ERROR("spec_store", LogFmt("failed to open tmp file: %s", tmp_path.c_str()));
      return false;
    }
    out << j.dump(2) << "\n";
    out.flush();
    if (!out.good()) {
      LOG_ERROR("spec_store", LogFmt("write failed: %s", tmp_path.c_str()));
      return false;
    }
  }

  if (rename(tmp_path.c_str(), file_path_.c_str()) != 0) {
    LOG_ERROR("spec_store", LogFmt("rename failed: %s -> %s", tmp_path.c_str(), file_path_.c_str()));
    return false;
  }

  return true;
}

std::string SpecStore::Create(const SpecRecord& spec, std::string& out_error) {
  std::lock_guard<std::mutex> lock(mu_);

  if (spec.spec_id.empty()) { out_error = "spec_id is required"; return ""; }
  if (spec.title.empty()) { out_error = "title is required"; return ""; }
  if (spec.group.empty()) { out_error = "group is required"; return ""; }
  if (spec.owner.empty()) { out_error = "owner is required"; return ""; }

  if (specs_.count(spec.spec_id)) {
    out_error = "spec_id already exists: " + spec.spec_id;
    return "";
  }

  SpecRecord s = spec;
  s.stage = SpecStage::S1_alignment;
  s.active = true;
  if (s.created_at.empty()) s.created_at = NowUTC();
  s.updated_at = s.created_at;

  specs_[s.spec_id] = s;

  // Generate intake task ID
  std::string intake_task_id = s.spec_id + "-T001";

  out_error = "";
  return intake_task_id;
}

std::string SpecStore::Progress(const std::string& spec_id, const std::string& target_stage) {
  std::lock_guard<std::mutex> lock(mu_);

  auto it = specs_.find(spec_id);
  if (it == specs_.end()) return "spec not found: " + spec_id;
  if (!it->second.active) return "spec is archived: " + spec_id;

  SpecRecord& s = it->second;
  SpecStage target = SpecStageFromStr(target_stage);
  int current_order = SpecStageOrder(s.stage);
  int target_order = SpecStageOrder(target);

  // Must advance exactly one step, or jump to archived from S8_complete
  if (target_order != current_order + 1) {
    return "illegal stage progression: " + std::string(SpecStageToStr(s.stage))
           + " -> " + target_stage + " (must advance sequentially)";
  }

  s.stage = target;
  s.updated_at = NowUTC();

  if (target == SpecStage::Archived) {
    s.active = false;
  }

  return "";
}

std::vector<SpecRecord> SpecStore::Query(const SpecQueryFilter& filter) const {
  std::lock_guard<std::mutex> lock(mu_);
  std::vector<SpecRecord> result;
  for (auto& [id, s] : specs_) {
    if (!s.active && filter.spec_id.empty()) continue;  // skip inactive unless querying by ID
    if (MatchesFilter(s, filter)) result.push_back(s);
  }
  return result;
}

const SpecRecord* SpecStore::Get(const std::string& spec_id) const {
  std::lock_guard<std::mutex> lock(mu_);
  auto it = specs_.find(spec_id);
  if (it == specs_.end()) return nullptr;
  return &it->second;
}

int SpecStore::Count() const {
  std::lock_guard<std::mutex> lock(mu_);
  int count = 0;
  for (auto& [id, s] : specs_) {
    if (s.active) count++;
  }
  return count;
}

bool SpecStore::MatchesFilter(const SpecRecord& s, const SpecQueryFilter& f) const {
  if (!f.spec_id.empty() && s.spec_id != f.spec_id) return false;
  if (!f.group.empty() && s.group != f.group) return false;
  if (!f.stage.empty() && SpecStageToStr(s.stage) != f.stage) return false;
  return true;
}
