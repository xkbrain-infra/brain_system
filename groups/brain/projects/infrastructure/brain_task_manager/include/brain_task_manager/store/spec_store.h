#pragma once
#include "brain_task_manager/core/types.h"
#include "brain_task_manager/core/logger.h"
#include <string>
#include <unordered_map>
#include <vector>
#include <mutex>

struct SpecQueryFilter {
  std::string spec_id;
  std::string group;
  std::string stage;
};

class SpecStore {
public:
  explicit SpecStore(const std::string& data_dir);

  // Load specs from JSON file. Returns number loaded.
  int Load();

  // Save specs to JSON file (atomic write). Returns true on success.
  bool Save();

  // Create a new spec. Returns intake task_id on success, empty string on failure.
  // Sets out_error if creation fails.
  std::string Create(const SpecRecord& spec, std::string& out_error);

  // Progress spec to target stage. Must be sequential (S1→S2→...→S8→archived).
  // Returns empty string on success, error message on failure.
  std::string Progress(const std::string& spec_id, const std::string& target_stage);

  // Query specs by filters.
  std::vector<SpecRecord> Query(const SpecQueryFilter& filter) const;

  // Get single spec by ID. Returns nullptr if not found.
  const SpecRecord* Get(const std::string& spec_id) const;

  // Total active spec count.
  int Count() const;

private:
  bool MatchesFilter(const SpecRecord& s, const SpecQueryFilter& f) const;

  std::string data_dir_;
  std::string file_path_;
  mutable std::mutex mu_;
  std::unordered_map<std::string, SpecRecord> specs_;
};
