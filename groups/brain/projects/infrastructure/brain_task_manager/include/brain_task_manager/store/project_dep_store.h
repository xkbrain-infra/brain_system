#pragma once
#include "brain_task_manager/core/types.h"
#include "brain_task_manager/core/logger.h"
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <mutex>

class ProjectDepStore {
public:
  explicit ProjectDepStore(const std::string& data_dir);

  // Load from JSON file. Returns number loaded.
  int Load();

  // Save to JSON file (atomic write). Returns true on success.
  bool Save();

  // Set dependencies for a project. Returns empty string or error (e.g. cycle).
  std::string Set(const std::string& project_id, const std::vector<std::string>& depends_on);

  // Query upstream dependencies for a project.
  std::vector<std::string> GetDependencies(const std::string& project_id) const;

  // Query downstream dependents (projects that depend on this one).
  std::vector<std::string> GetDownstream(const std::string& project_id) const;

  // Check if dependencies have been set for a project.
  bool HasDeps(const std::string& project_id) const;

private:
  bool DetectCycle(const std::string& start) const;

  std::string data_dir_;
  std::string file_path_;
  mutable std::mutex mu_;
  // project_id -> list of upstream project_ids
  std::unordered_map<std::string, std::vector<std::string>> deps_;
};
