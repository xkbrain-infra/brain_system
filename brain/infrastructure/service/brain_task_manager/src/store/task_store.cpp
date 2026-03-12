#include "brain_task_manager/store/task_store.h"
#include <fstream>
#include <unordered_set>

TaskStore::TaskStore(const std::string& data_dir, const FSMEngine& fsm)
  : data_dir_(data_dir), fsm_(fsm) {
  // Ensure trailing slash
  if (!data_dir_.empty() && data_dir_.back() != '/') data_dir_ += '/';
  file_path_ = data_dir_ + "tasks.json";
}

int TaskStore::Load() {
  std::lock_guard<std::mutex> lock(mu_);
  std::ifstream f(file_path_);
  if (!f.is_open()) {
    LOG_WARN("task_store", LogFmt("tasks file not found: %s, starting empty", file_path_.c_str()));
    return 0;
  }

  auto j = json::parse(f, nullptr, false);
  if (j.is_discarded() || !j.contains("tasks") || !j["tasks"].is_object()) {
    LOG_ERROR("task_store", LogFmt("failed to parse tasks file: %s", file_path_.c_str()));
    return 0;
  }

  tasks_.clear();
  for (auto& [key, val] : j["tasks"].items()) {
    Task t = Task::from_json(val);
    tasks_[t.task_id] = t;
  }

  LOG_INFO("task_store", LogFmt("loaded %d tasks from %s", (int)tasks_.size(), file_path_.c_str()));
  return static_cast<int>(tasks_.size());
}

bool TaskStore::Save() {
  std::lock_guard<std::mutex> lock(mu_);

  json j;
  j["tasks"] = json::object();
  for (auto& [id, t] : tasks_) {
    j["tasks"][id] = t.to_json();
  }

  // Atomic write: write to .tmp then rename
  std::string tmp_path = file_path_ + ".tmp";
  {
    std::ofstream out(tmp_path);
    if (!out.is_open()) {
      LOG_ERROR("task_store", LogFmt("failed to open tmp file: %s", tmp_path.c_str()));
      return false;
    }
    out << j.dump(2) << "\n";
    out.flush();
    if (!out.good()) {
      LOG_ERROR("task_store", LogFmt("write failed: %s", tmp_path.c_str()));
      return false;
    }
  }

  if (rename(tmp_path.c_str(), file_path_.c_str()) != 0) {
    LOG_ERROR("task_store", LogFmt("rename failed: %s -> %s", tmp_path.c_str(), file_path_.c_str()));
    return false;
  }

  return true;
}

std::string TaskStore::Create(const Task& task) {
  std::lock_guard<std::mutex> lock(mu_);

  if (task.task_id.empty()) return "task_id is required";
  if (task.title.empty()) return "title is required";
  if (task.owner.empty()) return "owner is required";
  if (!IsValidPriority(task.priority)) return "invalid priority: " + task.priority;

  if (tasks_.count(task.task_id)) return "task_id already exists: " + task.task_id;

  Task t = task;
  t.status = TaskStatus::Pending;
  t.active = true;
  t.version = 1;  // Initial version for CAS
  if (t.created_at.empty()) t.created_at = NowUTC();
  t.updated_at = t.created_at;

  tasks_[t.task_id] = t;
  return "";
}

std::string TaskStore::Update(const std::string& task_id, const json& fields, int64_t expected_version) {
  std::lock_guard<std::mutex> lock(mu_);

  auto it = tasks_.find(task_id);
  if (it == tasks_.end()) return "task not found: " + task_id;
  if (!it->second.active) return "task is deleted: " + task_id;

  Task& t = it->second;

  // CAS check: if expected_version >= 0, version must match
  if (expected_version >= 0 && t.version != static_cast<uint64_t>(expected_version)) {
    return "version conflict: expected " + std::to_string(expected_version) +
           ", actual " + std::to_string(t.version);
  }

  // Status change requires FSM validation
  if (fields.contains("status") && fields["status"].is_string()) {
    std::string new_status_str = fields["status"].get<std::string>();
    // Fix-9: reject unknown status strings explicitly
    if (!IsValidStatus(new_status_str)) {
      return "invalid status: " + new_status_str;
    }
    TaskStatus new_status = TaskStatusFromStr(new_status_str);
    if (!fsm_.CanTransition(t.status, new_status)) {
      return "illegal status transition: " + std::string(TaskStatusToStr(t.status))
             + " -> " + new_status_str;
    }
    t.status = new_status;
  }

  // Update other fields (only if present)
  if (fields.contains("owner") && fields["owner"].is_string())
    t.owner = fields["owner"].get<std::string>();
  if (fields.contains("priority") && fields["priority"].is_string()) {
    std::string p = fields["priority"].get<std::string>();
    if (!IsValidPriority(p)) return "invalid priority: " + p;
    t.priority = p;
  }
  if (fields.contains("title") && fields["title"].is_string())
    t.title = fields["title"].get<std::string>();
  if (fields.contains("description") && fields["description"].is_string())
    t.description = fields["description"].get<std::string>();
  if (fields.contains("deadline") && fields["deadline"].is_string())
    t.deadline = fields["deadline"].get<std::string>();
  if (fields.contains("depends_on") && fields["depends_on"].is_array()) {
    t.depends_on.clear();
    for (auto& d : fields["depends_on"]) {
      if (d.is_string()) t.depends_on.push_back(d.get<std::string>());
    }
  }
  if (fields.contains("tags") && fields["tags"].is_array()) {
    t.tags.clear();
    for (auto& tag : fields["tags"]) {
      if (tag.is_string()) t.tags.push_back(tag.get<std::string>());
    }
  }

  t.version++;  // Increment version on successful update
  t.updated_at = NowUTC();
  return "";
}

std::vector<Task> TaskStore::Query(const TaskQueryFilter& filter) const {
  std::lock_guard<std::mutex> lock(mu_);
  std::vector<Task> result;
  for (auto& [id, t] : tasks_) {
    if (!t.active) continue;
    if (MatchesFilter(t, filter)) result.push_back(t);
  }
  return result;
}

std::optional<Task> TaskStore::Get(const std::string& task_id) const {
  std::lock_guard<std::mutex> lock(mu_);
  auto it = tasks_.find(task_id);
  if (it == tasks_.end() || !it->second.active) return std::nullopt;
  return it->second;  // Return copy to eliminate TOCTOU risk
}

// Fix-7: check active=false before re-deleting
std::string TaskStore::Delete(const std::string& task_id) {
  std::lock_guard<std::mutex> lock(mu_);
  auto it = tasks_.find(task_id);
  if (it == tasks_.end()) return "task not found: " + task_id;
  if (!it->second.active) return "task not found: " + task_id;
  it->second.active = false;
  it->second.updated_at = NowUTC();
  return "";
}

TaskStats TaskStore::Stats(const std::string& spec_id) const {
  std::lock_guard<std::mutex> lock(mu_);
  TaskStats stats;
  stats.spec_id = spec_id;

  for (auto& [id, t] : tasks_) {
    if (!t.active) continue;
    if (!spec_id.empty() && t.spec_id != spec_id) continue;
    stats.total++;
    stats.by_status[TaskStatusToStr(t.status)]++;
    stats.by_priority[t.priority]++;
  }
  return stats;
}

PipelineCheckResult TaskStore::PipelineCheck(const std::string& spec_id) const {
  std::lock_guard<std::mutex> lock(mu_);
  PipelineCheckResult result;

  // Collect tasks for this spec
  std::unordered_map<std::string, Task> spec_tasks;
  for (auto& [id, t] : tasks_) {
    if (!t.active) continue;
    if (!spec_id.empty() && t.spec_id != spec_id) continue;
    spec_tasks[id] = t;
  }

  result.total_tasks = static_cast<int>(spec_tasks.size());

  // Build dependency graph
  std::unordered_map<std::string, std::vector<std::string>> graph;  // task -> depends_on
  std::unordered_map<std::string, int> in_degree;

  for (auto& [id, t] : spec_tasks) {
    if (!graph.count(id)) graph[id] = {};
    if (!in_degree.count(id)) in_degree[id] = 0;

    for (auto& dep : t.depends_on) {
      graph[id].push_back(dep);
      result.edges++;

      // Check missing dependencies
      if (!spec_tasks.count(dep)) {
        result.missing_dependencies.push_back(dep);
      }
      in_degree[dep]++;
    }
  }

  // Check for cycles using DFS
  std::unordered_set<std::string> visited;
  std::unordered_set<std::string> in_stack;

  std::function<bool(const std::string&, std::vector<std::string>&)> dfs =
    [&](const std::string& node, std::vector<std::string>& path) -> bool {
    visited.insert(node);
    in_stack.insert(node);
    path.push_back(node);

    if (graph.count(node)) {
      for (auto& dep : graph[node]) {
        if (!spec_tasks.count(dep)) continue;  // skip missing deps
        if (in_stack.count(dep)) {
          // Cycle found
          path.push_back(dep);
          return true;
        }
        if (!visited.count(dep)) {
          if (dfs(dep, path)) return true;
        }
      }
    }

    path.pop_back();
    in_stack.erase(node);
    return false;
  };

  for (auto& [id, _] : spec_tasks) {
    if (!visited.count(id)) {
      std::vector<std::string> path;
      if (dfs(id, path)) {
        result.cycle_detected = true;
        result.cycle_path = path;
        result.valid = false;
        break;
      }
    }
  }

  if (!result.missing_dependencies.empty()) {
    result.valid = false;
  }

  // Count ready vs blocked tasks
  for (auto& [id, t] : spec_tasks) {
    if (t.status == TaskStatus::Pending || t.status == TaskStatus::Blocked) {
      bool blocked = false;
      for (auto& dep : t.depends_on) {
        auto dep_it = spec_tasks.find(dep);
        if (dep_it != spec_tasks.end() &&
            dep_it->second.status != TaskStatus::Completed &&
            dep_it->second.status != TaskStatus::Archived) {
          blocked = true;
          break;
        }
      }
      if (blocked) result.blocked_tasks++;
      else result.ready_tasks++;
    }
  }

  return result;
}

std::vector<Task> TaskStore::GetAll() const {
  std::lock_guard<std::mutex> lock(mu_);
  std::vector<Task> result;
  for (auto& [id, t] : tasks_) {
    if (t.active) result.push_back(t);
  }
  return result;
}

int TaskStore::Count() const {
  std::lock_guard<std::mutex> lock(mu_);
  int count = 0;
  for (auto& [id, t] : tasks_) {
    if (t.active) count++;
  }
  return count;
}

bool TaskStore::MatchesFilter(const Task& t, const TaskQueryFilter& f) const {
  if (!f.task_id.empty() && t.task_id != f.task_id) return false;
  if (!f.spec_id.empty() && t.spec_id != f.spec_id) return false;
  if (!f.status.empty() && TaskStatusToStr(t.status) != f.status) return false;
  if (!f.group.empty() && t.group != f.group) return false;
  if (!f.owner.empty() && t.owner != f.owner) return false;
  return true;
}

bool TaskStore::DetectCycle(const std::string& start,
                            const std::unordered_map<std::string, std::vector<std::string>>& graph,
                            std::vector<std::string>& path) const {
  // Unused - cycle detection is done inline in PipelineCheck with DFS
  (void)start; (void)graph; (void)path;
  return false;
}
