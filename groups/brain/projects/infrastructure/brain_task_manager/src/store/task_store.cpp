#include "brain_task_manager/store/task_store.h"
#include "brain_task_manager/core/yaml_util.h"
#include <fstream>
#include <unordered_set>
#include <sys/stat.h>
#include <dirent.h>
#include <cerrno>

static bool MkdirP(const std::string& path) {
  for (size_t pos = 1; pos < path.size(); ++pos) {
    if (path[pos] == '/') {
      std::string partial = path.substr(0, pos);
      if (mkdir(partial.c_str(), 0755) != 0 && errno != EEXIST) return false;
    }
  }
  if (mkdir(path.c_str(), 0755) != 0 && errno != EEXIST) return false;
  return true;
}

TaskStore::TaskStore(const std::string& data_dir, const FSMEngine& fsm)
  : data_dir_(data_dir), fsm_(fsm) {
  if (!data_dir_.empty() && data_dir_.back() != '/') data_dir_ += '/';
}

// 递归扫描 data_dir，找所有 tasks.json 文件
void TaskStore::ScanDir(const std::string& dir, int depth) {
  if (depth > 6) return;
  DIR* d = opendir(dir.c_str());
  if (!d) return;

  struct dirent* entry;
  while ((entry = readdir(d)) != nullptr) {
    if (entry->d_name[0] == '.') continue;
    std::string name = entry->d_name;
    std::string path = dir + name;

    struct stat st;
    if (stat(path.c_str(), &st) != 0) continue;

    if (S_ISDIR(st.st_mode)) {
      ScanDir(path + "/", depth + 1);
    } else if (name == "tasks.yaml") {
      std::ifstream f(path);
      if (!f.is_open()) continue;
      json j = YamlToJson(YAML::Load(f));
      if (j.is_null() || !j.contains("tasks") || !j["tasks"].is_array()) {
        LOG_ERROR("task_store", LogFmt("failed to parse: %s", path.c_str()));
        continue;
      }
      for (auto& jt : j["tasks"]) {
        Task t = Task::from_json(jt);
        if (!t.task_id.empty()) tasks_[t.task_id] = t;
      }
    }
  }
  closedir(d);
}

int TaskStore::Load() {
  std::lock_guard<std::mutex> lock(mu_);
  tasks_.clear();
  ScanDir(data_dir_, 0);
  LOG_INFO("task_store", LogFmt("loaded %d tasks from %s",
           (int)tasks_.size(), data_dir_.c_str()));
  return static_cast<int>(tasks_.size());
}

// 将属于某个 project 的所有任务写入 tasks.json
bool TaskStore::SaveProject(const std::string& group, const std::string& project_id) {
  std::string dir = ProjectDataDir(data_dir_, group, project_id);
  if (!MkdirP(dir)) {
    LOG_ERROR("task_store", LogFmt("failed to create dir: %s", dir.c_str()));
    return false;
  }

  json j;
  j["tasks"] = json::array();
  for (auto& [id, t] : tasks_) {
    if (t.project_id == project_id && t.group == group) {
      j["tasks"].push_back(t.to_json());
    }
  }

  std::string file_path = dir + "tasks.yaml";
  std::string tmp_path  = file_path + ".tmp";
  {
    std::ofstream out(tmp_path);
    if (!out.is_open()) return false;
    out << JsonToYaml(j) << "\n";
    out.flush();
    if (!out.good()) return false;
  }
  return rename(tmp_path.c_str(), file_path.c_str()) == 0;
}

int TaskStore::Save() {
  std::lock_guard<std::mutex> lock(mu_);

  // 收集所有 (group, project_id) 组合
  std::unordered_map<std::string, std::pair<std::string,std::string>> projects;
  for (auto& [id, t] : tasks_) {
    if (!t.project_id.empty()) {
      std::string key = t.group + "|" + t.project_id;
      projects[key] = {t.group, t.project_id};
    }
  }

  int ok = 0;
  for (auto& [key, gp] : projects) {
    if (SaveProject(gp.first, gp.second)) ok++;
    else LOG_ERROR("task_store", LogFmt("failed to save tasks for: %s", key.c_str()));
  }
  return ok;
}

std::string TaskStore::Create(const Task& task) {
  std::lock_guard<std::mutex> lock(mu_);

  if (task.task_id.empty())    return "task_id is required";
  if (task.title.empty())      return "title is required";
  if (task.owner.empty())      return "owner is required";
  if (task.project_id.empty()) return "project_id is required";
  if (!IsValidPriority(task.priority)) return "invalid priority: " + task.priority;
  if (tasks_.count(task.task_id)) return "task_id already exists: " + task.task_id;

  Task t = task;
  t.status      = TaskStatus::Pending;
  t.active      = true;
  t.version     = 1;
  t.retry_count = 0;
  if (t.trigger_policy.empty()) t.trigger_policy = "manual";
  if (t.created_at.empty()) t.created_at = NowUTC();
  t.updated_at = t.created_at;

  tasks_[t.task_id] = t;
  return "";
}

std::string TaskStore::Update(const std::string& task_id, const json& fields,
                               int64_t expected_version) {
  std::lock_guard<std::mutex> lock(mu_);

  auto it = tasks_.find(task_id);
  if (it == tasks_.end())    return "task not found: " + task_id;
  if (!it->second.active)    return "task is deleted: " + task_id;

  Task& t = it->second;

  if (expected_version >= 0 && t.version != static_cast<uint64_t>(expected_version)) {
    return "version conflict: expected " + std::to_string(expected_version) +
           ", actual " + std::to_string(t.version);
  }

  // 状态变更：FSM 验证 + 状态驱动字段自动维护
  if (fields.contains("status") && fields["status"].is_string()) {
    std::string new_status_str = fields["status"].get<std::string>();
    if (!IsValidStatus(new_status_str)) return "invalid status: " + new_status_str;

    TaskStatus new_status = TaskStatusFromStr(new_status_str);
    if (!fsm_.CanTransition(t.status, new_status)) {
      return "illegal status transition: " + std::string(TaskStatusToStr(t.status))
             + " -> " + new_status_str;
    }

    TaskStatus old_status = t.status;
    t.status = new_status;

    // 进入 Blocked：写入阻塞原因
    if (new_status == TaskStatus::Blocked) {
      if (fields.contains("blocked_reason") && fields["blocked_reason"].is_string())
        t.blocked_reason = fields["blocked_reason"].get<std::string>();
    }

    // 离开 Blocked（unblock）或 Review→InProgress（reject/rework）：
    // 自增 retry_count，清空 blocked_reason 和 worker_id
    bool is_unblock = (old_status == TaskStatus::Blocked && new_status == TaskStatus::Ready);
    bool is_rework  = (old_status == TaskStatus::Review  && new_status == TaskStatus::InProgress);
    if (is_unblock || is_rework) {
      t.retry_count++;
      t.blocked_reason.clear();
      t.worker_id.clear();
    }

    // 进入 InProgress（首次派发，非 rework）：记录执行者和参与者
    if (new_status == TaskStatus::InProgress && !is_rework) {
      if (fields.contains("worker_id") && fields["worker_id"].is_string()) {
        t.worker_id = fields["worker_id"].get<std::string>();
        // 自动加入 participants（若不存在）
        bool found = false;
        for (auto& p : t.participants) if (p == t.worker_id) { found = true; break; }
        if (!found && !t.worker_id.empty()) t.participants.push_back(t.worker_id);
      }
    }

    // 进入终态（Completed/Failed）：写入 result 和 last_log_ref
    if (new_status == TaskStatus::Completed || new_status == TaskStatus::Failed) {
      if (fields.contains("result") && fields["result"].is_string())
        t.result = fields["result"].get<std::string>();
      if (fields.contains("last_log_ref") && fields["last_log_ref"].is_string())
        t.last_log_ref = fields["last_log_ref"].get<std::string>();
    }
  }

  // 更新其他字段（仅当字段存在时）
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
  if (fields.contains("review_by") && fields["review_by"].is_string())
    t.review_by = fields["review_by"].get<std::string>();
  if (fields.contains("next_check_at") && fields["next_check_at"].is_string())
    t.next_check_at = fields["next_check_at"].get<std::string>();
  if (fields.contains("escalation_policy") && fields["escalation_policy"].is_string())
    t.escalation_policy = fields["escalation_policy"].get<std::string>();
  if (fields.contains("artifact_refs") && fields["artifact_refs"].is_array()) {
    t.artifact_refs.clear();
    for (auto& a : fields["artifact_refs"])
      if (a.is_string()) t.artifact_refs.push_back(a.get<std::string>());
  }
  if (fields.contains("participants") && fields["participants"].is_array()) {
    t.participants.clear();
    for (auto& p : fields["participants"])
      if (p.is_string()) t.participants.push_back(p.get<std::string>());
  }
  if (fields.contains("todo_list") && fields["todo_list"].is_array()) {
    t.todo_list.clear();
    for (auto& item : fields["todo_list"])
      t.todo_list.push_back(TodoItem::from_json(item));
  }
  if (fields.contains("depends_on") && fields["depends_on"].is_array()) {
    t.depends_on.clear();
    for (auto& d : fields["depends_on"])
      if (d.is_string()) t.depends_on.push_back(d.get<std::string>());
  }
  if (fields.contains("tags") && fields["tags"].is_array()) {
    t.tags.clear();
    for (auto& tag : fields["tags"])
      if (tag.is_string()) t.tags.push_back(tag.get<std::string>());
  }

  t.version++;
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
  return it->second;
}

std::string TaskStore::Delete(const std::string& task_id) {
  std::lock_guard<std::mutex> lock(mu_);
  auto it = tasks_.find(task_id);
  if (it == tasks_.end() || !it->second.active) return "task not found: " + task_id;
  it->second.active     = false;
  it->second.updated_at = NowUTC();
  return "";
}

TaskStats TaskStore::Stats(const std::string& project_id) const {
  std::lock_guard<std::mutex> lock(mu_);
  TaskStats stats;
  stats.project_id = project_id;
  for (auto& [id, t] : tasks_) {
    if (!t.active) continue;
    if (!project_id.empty() && t.project_id != project_id) continue;
    stats.total++;
    stats.by_status[TaskStatusToStr(t.status)]++;
    stats.by_priority[t.priority]++;
  }
  return stats;
}

PipelineCheckResult TaskStore::PipelineCheck(const std::string& project_id) const {
  std::lock_guard<std::mutex> lock(mu_);
  PipelineCheckResult result;

  std::unordered_map<std::string, Task> proj_tasks;
  for (auto& [id, t] : tasks_) {
    if (!t.active) continue;
    if (!project_id.empty() && t.project_id != project_id) continue;
    proj_tasks[id] = t;
  }

  result.total_tasks = static_cast<int>(proj_tasks.size());

  std::unordered_map<std::string, std::vector<std::string>> graph;
  for (auto& [id, t] : proj_tasks) {
    if (!graph.count(id)) graph[id] = {};
    for (auto& dep : t.depends_on) {
      graph[id].push_back(dep);
      result.edges++;
      if (!proj_tasks.count(dep)) result.missing_dependencies.push_back(dep);
    }
  }

  // DFS 环检测
  std::unordered_set<std::string> visited, in_stack;
  std::function<bool(const std::string&, std::vector<std::string>&)> dfs =
    [&](const std::string& node, std::vector<std::string>& path) -> bool {
    visited.insert(node);
    in_stack.insert(node);
    path.push_back(node);
    for (auto& dep : graph[node]) {
      if (!proj_tasks.count(dep)) continue;
      if (in_stack.count(dep)) { path.push_back(dep); return true; }
      if (!visited.count(dep) && dfs(dep, path)) return true;
    }
    path.pop_back();
    in_stack.erase(node);
    return false;
  };

  for (auto& [id, _] : proj_tasks) {
    if (!visited.count(id)) {
      std::vector<std::string> path;
      if (dfs(id, path)) {
        result.cycle_detected = true;
        result.cycle_path     = path;
        result.valid          = false;
        break;
      }
    }
  }

  if (!result.missing_dependencies.empty()) result.valid = false;

  for (auto& [id, t] : proj_tasks) {
    if (t.status == TaskStatus::Pending || t.status == TaskStatus::Blocked) {
      bool blocked = false;
      for (auto& dep : t.depends_on) {
        auto dep_it = proj_tasks.find(dep);
        if (dep_it != proj_tasks.end() &&
            dep_it->second.status != TaskStatus::Completed &&
            dep_it->second.status != TaskStatus::Archived) {
          blocked = true; break;
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
  for (auto& [id, t] : tasks_) if (t.active) count++;
  return count;
}

bool TaskStore::MatchesFilter(const Task& t, const TaskQueryFilter& f) const {
  if (!f.task_id.empty()    && t.task_id    != f.task_id)              return false;
  if (!f.project_id.empty() && t.project_id != f.project_id)           return false;
  if (!f.status.empty()     && TaskStatusToStr(t.status) != f.status)  return false;
  if (!f.group.empty()      && t.group      != f.group)                return false;
  if (!f.owner.empty()      && t.owner      != f.owner)                return false;
  return true;
}
