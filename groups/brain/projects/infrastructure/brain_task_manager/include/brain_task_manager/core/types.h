#pragma once
#include <string>
#include <vector>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

inline std::string JsonAsString(const json& j, const char* key, const std::string& fallback = "") {
  if (!j.contains(key) || j[key].is_null()) return fallback;
  const auto& v = j[key];
  if (v.is_string()) return v.get<std::string>();
  if (v.is_boolean()) return v.get<bool>() ? "true" : "false";
  if (v.is_number_integer()) return std::to_string(v.get<int64_t>());
  if (v.is_number_unsigned()) return std::to_string(v.get<uint64_t>());
  if (v.is_number_float()) return v.dump();
  return v.dump();
}

inline std::vector<std::string> JsonAsStringVector(const json& j, const char* key) {
  std::vector<std::string> result;
  if (!j.contains(key) || !j[key].is_array()) return result;
  for (const auto& item : j[key]) {
    if (item.is_null()) continue;
    if (item.is_string()) {
      result.push_back(item.get<std::string>());
    } else if (item.is_boolean()) {
      result.push_back(item.get<bool>() ? "true" : "false");
    } else if (item.is_number_integer()) {
      result.push_back(std::to_string(item.get<int64_t>()));
    } else if (item.is_number_unsigned()) {
      result.push_back(std::to_string(item.get<uint64_t>()));
    } else if (item.is_number_float()) {
      result.push_back(item.dump());
    } else {
      result.push_back(item.dump());
    }
  }
  return result;
}

// ========== Task Status ==========

enum class TaskStatus {
  // ── 待派发 ──────────────────────────────────────────────────────────────
  Pending,      // 初始态：依赖未满足，尚不可派发
  Ready,        // 依赖已满足，等待 orchestrator dispatch
  // ── 执行中 ──────────────────────────────────────────────────────────────
  InProgress,   // worker 已接受任务，正在执行
  Review,       // 实现完成，等待 review / test
  Verified,     // review/test 通过，等待 orchestrator 提交 Completed
  Blocked,      // 执行中遇到阻塞，需要 orchestrator 介入（非终态，可恢复）
  // ── 终态 ────────────────────────────────────────────────────────────────
  Completed,    // 验收通过，任务完成
  Failed,       // 不可恢复失败
  Cancelled,    // 已取消
  Archived      // 归档（terminal，无出边）
};

inline const char* TaskStatusToStr(TaskStatus s) {
  switch (s) {
    case TaskStatus::Pending:     return "pending";
    case TaskStatus::Ready:       return "ready";
    case TaskStatus::InProgress:  return "in_progress";
    case TaskStatus::Review:      return "review";
    case TaskStatus::Verified:    return "verified";
    case TaskStatus::Blocked:     return "blocked";
    case TaskStatus::Completed:   return "completed";
    case TaskStatus::Failed:      return "failed";
    case TaskStatus::Cancelled:   return "cancelled";
    case TaskStatus::Archived:    return "archived";
  }
  return "pending";
}

inline TaskStatus TaskStatusFromStr(const std::string& s) {
  if (s == "pending")     return TaskStatus::Pending;
  if (s == "ready")       return TaskStatus::Ready;
  if (s == "in_progress") return TaskStatus::InProgress;
  if (s == "review")      return TaskStatus::Review;
  if (s == "verified")    return TaskStatus::Verified;
  if (s == "blocked")     return TaskStatus::Blocked;
  if (s == "completed")   return TaskStatus::Completed;
  if (s == "failed")      return TaskStatus::Failed;
  if (s == "cancelled")   return TaskStatus::Cancelled;
  if (s == "archived")    return TaskStatus::Archived;
  return TaskStatus::Pending;
}

inline bool IsValidStatus(const std::string& s) {
  return s == "pending" || s == "ready" || s == "in_progress"
      || s == "review"  || s == "verified" || s == "blocked"
      || s == "completed" || s == "failed" || s == "cancelled" || s == "archived";
}

inline bool IsValidPriority(const std::string& p) {
  return p == "critical" || p == "high" || p == "normal" || p == "low";
}

// ========== Spec Stage (项目交付生命周期，S1→S8 顺序推进) ==========

enum class SpecStage {
  S1_alignment, S2_requirements, S3_research, S4_analysis,
  S5_solution, S6_tasks, S7_verification, S8_complete, Archived
};

inline const char* SpecStageToStr(SpecStage s) {
  switch (s) {
    case SpecStage::S1_alignment:     return "S1_alignment";
    case SpecStage::S2_requirements:  return "S2_requirements";
    case SpecStage::S3_research:      return "S3_research";
    case SpecStage::S4_analysis:      return "S4_analysis";
    case SpecStage::S5_solution:      return "S5_solution";
    case SpecStage::S6_tasks:         return "S6_tasks";
    case SpecStage::S7_verification:  return "S7_verification";
    case SpecStage::S8_complete:      return "S8_complete";
    case SpecStage::Archived:         return "archived";
  }
  return "S1_alignment";
}

inline SpecStage SpecStageFromStr(const std::string& s) {
  if (s == "S1_alignment")     return SpecStage::S1_alignment;
  if (s == "S2_requirements")  return SpecStage::S2_requirements;
  if (s == "S3_research")      return SpecStage::S3_research;
  if (s == "S4_analysis")      return SpecStage::S4_analysis;
  if (s == "S5_solution")      return SpecStage::S5_solution;
  if (s == "S6_tasks")         return SpecStage::S6_tasks;
  if (s == "S7_verification")  return SpecStage::S7_verification;
  if (s == "S8_complete")      return SpecStage::S8_complete;
  if (s == "archived")         return SpecStage::Archived;
  return SpecStage::S1_alignment;
}

inline bool IsValidStage(const std::string& s) {
  return s == "S1_alignment" || s == "S2_requirements" || s == "S3_research"
      || s == "S4_analysis" || s == "S5_solution" || s == "S6_tasks"
      || s == "S7_verification" || s == "S8_complete" || s == "archived";
}

inline int SpecStageOrder(SpecStage s) { return static_cast<int>(s); }

// ========== TodoItem (任务内子检查项) ==========

struct TodoItem {
  std::string text;
  bool done = false;

  json to_json() const {
    return json{{"text", text}, {"done", done}};
  }

  static TodoItem from_json(const json& j) {
    TodoItem t;
    t.text = j.value("text", "");
    t.done = j.value("done", false);
    return t;
  }
};

// ========== TaskEvent (任务状态变更事件，append-only) ==========
// event_type 取值:
//   task.created / task.assigned / task.accepted / task.active /
//   task.blocked / task.unblocked / task.review_requested /
//   task.verified / task.done / task.failed / task.cancelled / task.archived

struct TaskEvent {
  std::string event_type;
  std::string task_id;
  std::string project_id;
  std::string group;
  std::string actor;      // 触发者 agent_id
  std::string timestamp;
  std::string note;       // 可选：补充说明

  json to_json() const {
    return json{
      {"event_type", event_type},
      {"task_id",    task_id},
      {"project_id", project_id},
      {"group",      group},
      {"actor",      actor},
      {"timestamp",  timestamp},
      {"note",       note}
    };
  }

  static TaskEvent from_json(const json& j) {
    TaskEvent e;
    e.event_type = JsonAsString(j, "event_type");
    e.task_id    = JsonAsString(j, "task_id");
    e.project_id = JsonAsString(j, "project_id");
    e.group      = JsonAsString(j, "group");
    e.actor      = JsonAsString(j, "actor");
    e.timestamp  = JsonAsString(j, "timestamp");
    e.note       = JsonAsString(j, "note");
    return e;
  }
};

// ========== Task 数据模型 ==========

struct Task {
  // ── 身份 ──────────────────────────────────────────────────────────────
  std::string task_id;
  std::string project_id;   // 所属 project（必填），对应 ProjectRecord.project_id
  std::string group;        // 团队/项目分组，与 project 一致（如 "org/brain_system"）

  // ── 内容 ──────────────────────────────────────────────────────────────
  std::string title;
  std::string description;
  std::string priority;       // critical|high|normal|low
  std::string deadline;       // ISO 8601: YYYY-MM-DDTHH:MM:SSZ，可为空
  std::string trigger_policy; // manual|auto|scheduled，默认 manual

  // ── 人员 ──────────────────────────────────────────────────────────────
  std::string owner;                       // 任务负责人（accountable），创建时指定
  std::string worker_id;                   // 当前执行者（assignee），orchestrator 派发时填写
  std::vector<std::string> participants;   // 所有参与者（含 worker、reviewer 等）
  std::string review_by;                   // 指定 reviewer

  // ── 状态 ──────────────────────────────────────────────────────────────
  TaskStatus  status = TaskStatus::Pending;
  std::string blocked_reason;   // 仅 Blocked 时有效，unblock 后自动清空
  uint32_t    retry_count = 0;  // Blocked→Ready 或 Review→InProgress(reject) 时自增

  // ── 产出 ──────────────────────────────────────────────────────────────
  std::string result;                      // 完成/失败时的输出摘要
  std::vector<std::string> artifact_refs;  // 产出物引用（文件路径/URL）
  std::string last_log_ref;                // 最近日志引用

  // ── 子任务清单 ────────────────────────────────────────────────────────
  std::vector<TodoItem> todo_list;         // 任务内检查项

  // ── 依赖 & 调度 & 标签 ────────────────────────────────────────────────
  std::vector<std::string> depends_on;     // 依赖的 task_id 列表（同 project 内）
  std::vector<std::string> tags;
  std::string next_check_at;               // 下次检查时间（ISO 8601）
  std::string escalation_policy;           // 升级策略（如 "notify_pmo_after_2h"）

  // ── 元数据 ────────────────────────────────────────────────────────────
  std::string created_at;
  std::string updated_at;
  bool     active  = true;
  uint64_t version = 0;    // CAS 乐观锁

  json to_json() const {
    json todo_json = json::array();
    for (auto& t : todo_list) todo_json.push_back(t.to_json());

    return json{
      {"task_id",           task_id},
      {"project_id",        project_id},
      {"group",             group},
      {"title",             title},
      {"description",       description},
      {"priority",          priority},
      {"deadline",          deadline},
      {"trigger_policy",    trigger_policy},
      {"owner",             owner},
      {"worker_id",         worker_id},
      {"participants",      participants},
      {"review_by",         review_by},
      {"status",            TaskStatusToStr(status)},
      {"blocked_reason",    blocked_reason},
      {"retry_count",       retry_count},
      {"result",            result},
      {"artifact_refs",     artifact_refs},
      {"last_log_ref",      last_log_ref},
      {"todo_list",         todo_json},
      {"depends_on",        depends_on},
      {"tags",              tags},
      {"next_check_at",     next_check_at},
      {"escalation_policy", escalation_policy},
      {"created_at",        created_at},
      {"updated_at",        updated_at},
      {"version",           version}
    };
  }

  static Task from_json(const json& j) {
    Task t;
    t.task_id           = JsonAsString(j, "task_id");
    t.project_id        = JsonAsString(j, "project_id");
    t.group             = JsonAsString(j, "group");
    t.title             = JsonAsString(j, "title");
    t.description       = JsonAsString(j, "description");
    t.priority          = JsonAsString(j, "priority", "normal");
    t.deadline          = JsonAsString(j, "deadline");
    t.trigger_policy    = JsonAsString(j, "trigger_policy", "manual");
    t.owner             = JsonAsString(j, "owner");
    t.worker_id         = JsonAsString(j, "worker_id");
    t.review_by         = JsonAsString(j, "review_by");
    t.status            = TaskStatusFromStr(JsonAsString(j, "status", "pending"));
    t.blocked_reason    = JsonAsString(j, "blocked_reason");
    t.retry_count       = j.value("retry_count", 0u);
    t.result            = JsonAsString(j, "result");
    t.last_log_ref      = JsonAsString(j, "last_log_ref");
    t.next_check_at     = JsonAsString(j, "next_check_at");
    t.escalation_policy = JsonAsString(j, "escalation_policy");
    t.created_at        = JsonAsString(j, "created_at");
    t.updated_at        = JsonAsString(j, "updated_at");
    t.active            = j.value("active", true);
    t.version           = j.value("version", uint64_t(0));

    t.participants = JsonAsStringVector(j, "participants");
    t.artifact_refs = JsonAsStringVector(j, "artifact_refs");
    if (j.contains("todo_list") && j["todo_list"].is_array())
      for (auto& item : j["todo_list"]) t.todo_list.push_back(TodoItem::from_json(item));
    t.depends_on = JsonAsStringVector(j, "depends_on");
    t.tags = JsonAsStringVector(j, "tags");
    return t;
  }
};

// ========== ProjectRecord (项目元数据，含交付阶段) ==========

struct ProjectRecord {
  std::string project_id;
  std::string group;      // 如 "org/brain_system"
  std::string title;
  std::string owner;      // PMO agent
  SpecStage   stage = SpecStage::S1_alignment;
  std::string created_at;
  std::string updated_at;
  bool active = true;

  json to_json() const {
    return json{
      {"project_id", project_id}, {"group", group},
      {"title", title}, {"owner", owner},
      {"stage", SpecStageToStr(stage)},
      {"created_at", created_at}, {"updated_at", updated_at}
    };
  }

  static ProjectRecord from_json(const json& j) {
    ProjectRecord p;
    p.project_id = JsonAsString(j, "project_id");
    p.group      = JsonAsString(j, "group");
    p.title      = JsonAsString(j, "title");
    p.owner      = JsonAsString(j, "owner");
    p.stage      = SpecStageFromStr(JsonAsString(j, "stage", "S1_alignment"));
    p.created_at = JsonAsString(j, "created_at");
    p.updated_at = JsonAsString(j, "updated_at");
    p.active     = j.value("active", true);
    return p;
  }
};

// ========== 向后兼容别名 ==========
// 旧代码中的 SpecRecord 现在是 ProjectRecord
using SpecRecord = ProjectRecord;

// ========== Utility ==========

inline std::string NowUTC() {
  char buf[32];
  time_t now = time(nullptr);
  struct tm tm_info;
  gmtime_r(&now, &tm_info);
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &tm_info);
  return buf;
}

// 返回 project 的数据目录：{data_dir}/{group}/{project_id}/
// 例: data_dir="/xkagent_infra/runtime/data/brain_task_manager/"
//     group="brain_system", project_id="BS-026"
//   → "/xkagent_infra/runtime/data/brain_task_manager/brain_system/BS-026/"
inline std::string ProjectDataDir(const std::string& data_dir,
                                   const std::string& group,
                                   const std::string& project_id) {
  std::string dir = data_dir;
  if (!dir.empty() && dir.back() != '/') dir += '/';
  dir += group + '/' + project_id + '/';
  return dir;
}
