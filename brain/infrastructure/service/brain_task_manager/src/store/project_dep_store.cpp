#include "brain_task_manager/store/project_dep_store.h"
#include <fstream>
#include <algorithm>

ProjectDepStore::ProjectDepStore(const std::string& data_dir) : data_dir_(data_dir) {
  if (!data_dir_.empty() && data_dir_.back() != '/') data_dir_ += '/';
  file_path_ = data_dir_ + "project_dependencies.json";
}

int ProjectDepStore::Load() {
  std::lock_guard<std::mutex> lock(mu_);
  std::ifstream f(file_path_);
  if (!f.is_open()) {
    LOG_WARN("project_dep", LogFmt("deps file not found: %s, starting empty", file_path_.c_str()));
    return 0;
  }

  auto j = json::parse(f, nullptr, false);
  if (j.is_discarded() || !j.contains("dependencies") || !j["dependencies"].is_object()) {
    LOG_ERROR("project_dep", LogFmt("failed to parse deps file: %s", file_path_.c_str()));
    return 0;
  }

  deps_.clear();
  for (auto& [key, val] : j["dependencies"].items()) {
    std::vector<std::string> dep_list;
    if (val.is_array()) {
      for (auto& d : val) {
        if (d.is_string()) dep_list.push_back(d.get<std::string>());
      }
    }
    deps_[key] = dep_list;
  }

  LOG_INFO("project_dep", LogFmt("loaded %d project deps from %s", (int)deps_.size(), file_path_.c_str()));
  return static_cast<int>(deps_.size());
}

bool ProjectDepStore::Save() {
  std::lock_guard<std::mutex> lock(mu_);

  json j;
  j["dependencies"] = json::object();
  for (auto& [id, dep_list] : deps_) {
    j["dependencies"][id] = dep_list;
  }

  std::string tmp_path = file_path_ + ".tmp";
  {
    std::ofstream out(tmp_path);
    if (!out.is_open()) {
      LOG_ERROR("project_dep", LogFmt("failed to open tmp file: %s", tmp_path.c_str()));
      return false;
    }
    out << j.dump(2) << "\n";
    out.flush();
    if (!out.good()) {
      LOG_ERROR("project_dep", LogFmt("write failed: %s", tmp_path.c_str()));
      return false;
    }
  }

  if (rename(tmp_path.c_str(), file_path_.c_str()) != 0) {
    LOG_ERROR("project_dep", LogFmt("rename failed: %s -> %s", tmp_path.c_str(), file_path_.c_str()));
    return false;
  }

  return true;
}

std::string ProjectDepStore::Set(const std::string& project_id,
                                  const std::vector<std::string>& depends_on) {
  std::lock_guard<std::mutex> lock(mu_);

  // Deduplicate and exclude self-reference
  std::vector<std::string> cleaned;
  std::unordered_set<std::string> seen;
  for (auto& d : depends_on) {
    if (d == project_id) continue;  // no self-loop
    if (seen.count(d)) continue;    // dedup
    seen.insert(d);
    cleaned.push_back(d);
  }

  // Temporarily set to check for cycles
  auto old = deps_[project_id];
  deps_[project_id] = cleaned;

  if (DetectCycle(project_id)) {
    deps_[project_id] = old;  // rollback
    return "CYCLE_DETECTED: setting these dependencies would create a cycle";
  }

  return "";
}

std::vector<std::string> ProjectDepStore::GetDependencies(const std::string& project_id) const {
  std::lock_guard<std::mutex> lock(mu_);
  auto it = deps_.find(project_id);
  if (it == deps_.end()) return {};
  return it->second;
}

std::vector<std::string> ProjectDepStore::GetDownstream(const std::string& project_id) const {
  std::lock_guard<std::mutex> lock(mu_);
  std::vector<std::string> result;
  for (auto& [id, dep_list] : deps_) {
    for (auto& d : dep_list) {
      if (d == project_id) {
        result.push_back(id);
        break;
      }
    }
  }
  return result;
}

bool ProjectDepStore::HasDeps(const std::string& project_id) const {
  std::lock_guard<std::mutex> lock(mu_);
  return deps_.count(project_id) > 0;
}

bool ProjectDepStore::DetectCycle(const std::string& start) const {
  // DFS cycle detection (mu_ already held by caller)
  std::unordered_set<std::string> visited;
  std::unordered_set<std::string> in_stack;

  std::function<bool(const std::string&)> dfs = [&](const std::string& node) -> bool {
    visited.insert(node);
    in_stack.insert(node);

    auto it = deps_.find(node);
    if (it != deps_.end()) {
      for (auto& dep : it->second) {
        if (in_stack.count(dep)) return true;  // cycle
        if (!visited.count(dep)) {
          if (dfs(dep)) return true;
        }
      }
    }

    in_stack.erase(node);
    return false;
  };

  return dfs(start);
}
