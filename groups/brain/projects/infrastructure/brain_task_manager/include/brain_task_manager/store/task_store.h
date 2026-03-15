#pragma once
#include "brain_task_manager/core/types.h"
#include "brain_task_manager/core/logger.h"
#include "brain_task_manager/engine/fsm_engine.h"
#include <string>
#include <unordered_map>
#include <vector>
#include <mutex>
#include <functional>

#include <optional>

struct TaskQueryFilter {
  std::string task_id;
  std::string spec_id;
  std::string status;
  std::string group;
  std::string owner;
};

struct TaskStats {
  std::string spec_id;
  int total = 0;
  std::unordered_map<std::string, int> by_status;
  std::unordered_map<std::string, int> by_priority;
};

struct PipelineCheckResult {
  bool valid = true;
  int total_tasks = 0;
  int edges = 0;
  int ready_tasks = 0;
  int blocked_tasks = 0;
  bool cycle_detected = false;
  std::vector<std::string> cycle_path;
  std::vector<std::string> missing_dependencies;
  std::vector<std::string> flow_violations;
};

class TaskStore {
public:
  TaskStore(const std::string& data_dir, const FSMEngine& fsm);

  // Load tasks from JSON file. Returns number loaded.
  int Load();

  // Save tasks to JSON file (atomic write). Returns true on success.
  bool Save();

  // Create a new task. Returns empty string on success, error message on failure.
  std::string Create(const Task& task);

  // Update task fields. Status changes validated by FSM.
  // If expected_version >= 0, performs CAS check (version must match).
  // Returns empty string on success, error message on failure.
  std::string Update(const std::string& task_id, const json& fields, int64_t expected_version = -1);

  // Query tasks by filters. All filters combined with AND.
  std::vector<Task> Query(const TaskQueryFilter& filter) const;

  // Get single task by ID. Returns std::nullopt if not found.
  std::optional<Task> Get(const std::string& task_id) const;

  // Logical delete (active=false). Returns empty string or error.
  std::string Delete(const std::string& task_id);

  // Get stats for a spec_id.
  TaskStats Stats(const std::string& spec_id) const;

  // Pipeline check: validate dependency graph for a spec_id.
  PipelineCheckResult PipelineCheck(const std::string& spec_id) const;

  // Get all active tasks (for scheduler scanning).
  std::vector<Task> GetAll() const;

  // Total active task count.
  int Count() const;

private:
  bool MatchesFilter(const Task& t, const TaskQueryFilter& f) const;
  bool DetectCycle(const std::string& start,
                   const std::unordered_map<std::string, std::vector<std::string>>& graph,
                   std::vector<std::string>& path) const;

  std::string data_dir_;
  std::string file_path_;
  const FSMEngine& fsm_;
  mutable std::mutex mu_;
  std::unordered_map<std::string, Task> tasks_;
};
