#pragma once
#include <string>
#include <vector>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

// ========== Task Status (backward compatible with task_manager C) ==========

enum class TaskStatus {
  Pending, InProgress, Blocked, Completed, Failed, Cancelled, Archived
};

inline const char* TaskStatusToStr(TaskStatus s) {
  switch (s) {
    case TaskStatus::Pending:     return "pending";
    case TaskStatus::InProgress:  return "in_progress";
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
  if (s == "in_progress") return TaskStatus::InProgress;
  if (s == "blocked")     return TaskStatus::Blocked;
  if (s == "completed")   return TaskStatus::Completed;
  if (s == "failed")      return TaskStatus::Failed;
  if (s == "cancelled")   return TaskStatus::Cancelled;
  if (s == "archived")    return TaskStatus::Archived;
  return TaskStatus::Pending;
}

// Fix-9/Fix-5: Validate status string before conversion
inline bool IsValidStatus(const std::string& s) {
  return s == "pending" || s == "in_progress" || s == "blocked"
      || s == "completed" || s == "failed" || s == "cancelled"
      || s == "archived";
}

inline bool IsValidPriority(const std::string& p) {
  return p == "critical" || p == "high" || p == "normal" || p == "low";
}

// ========== Spec Stage ==========

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

// Fix-6: Validate stage string before conversion
inline bool IsValidStage(const std::string& s) {
  return s == "S1_alignment" || s == "S2_requirements" || s == "S3_research"
      || s == "S4_analysis" || s == "S5_solution" || s == "S6_tasks"
      || s == "S7_verification" || s == "S8_complete" || s == "archived";
}

inline int SpecStageOrder(SpecStage s) { return static_cast<int>(s); }

// ========== Task data model ==========

struct Task {
  std::string task_id;
  std::string title;
  std::string owner;
  std::string priority;  // critical|high|normal|low
  TaskStatus  status = TaskStatus::Pending;
  std::string spec_id;
  std::string group;
  std::string description;
  std::string deadline;
  std::vector<std::string> depends_on;
  std::vector<std::string> tags;
  std::string created_at;
  std::string updated_at;
  bool active = true;
  uint64_t version = 0;  // CAS optimistic locking for race condition prevention

  json to_json() const {
    return json{
      {"task_id", task_id}, {"title", title}, {"owner", owner},
      {"priority", priority}, {"status", TaskStatusToStr(status)},
      {"spec_id", spec_id}, {"group", group}, {"description", description},
      {"deadline", deadline}, {"depends_on", depends_on}, {"tags", tags},
      {"created_at", created_at}, {"updated_at", updated_at},
      {"version", version}
    };
  }

  static Task from_json(const json& j) {
    Task t;
    t.task_id     = j.value("task_id", "");
    t.title       = j.value("title", "");
    t.owner       = j.value("owner", "");
    t.priority    = j.value("priority", "normal");
    t.status      = TaskStatusFromStr(j.value("status", "pending"));
    t.spec_id     = j.value("spec_id", "");
    t.group       = j.value("group", "");
    t.description = j.value("description", "");
    t.deadline    = j.value("deadline", "");
    t.created_at  = j.value("created_at", "");
    t.updated_at  = j.value("updated_at", "");
    t.active      = j.value("active", true);
    t.version     = j.value("version", 0);
    if (j.contains("depends_on") && j["depends_on"].is_array())
      for (auto& d : j["depends_on"]) t.depends_on.push_back(d.get<std::string>());
    if (j.contains("tags") && j["tags"].is_array())
      for (auto& tag : j["tags"]) t.tags.push_back(tag.get<std::string>());
    return t;
  }
};

// ========== Spec record model ==========

struct SpecRecord {
  std::string spec_id;
  std::string title;
  std::string group;
  std::string owner;
  SpecStage   stage = SpecStage::S1_alignment;
  std::string created_at;
  std::string updated_at;
  bool active = true;

  json to_json() const {
    return json{
      {"spec_id", spec_id}, {"title", title}, {"group", group},
      {"owner", owner}, {"stage", SpecStageToStr(stage)},
      {"created_at", created_at}, {"updated_at", updated_at}
    };
  }

  static SpecRecord from_json(const json& j) {
    SpecRecord s;
    s.spec_id    = j.value("spec_id", "");
    s.title      = j.value("title", "");
    s.group      = j.value("group", "");
    s.owner      = j.value("owner", "");
    s.stage      = SpecStageFromStr(j.value("stage", "S1_alignment"));
    s.created_at = j.value("created_at", "");
    s.updated_at = j.value("updated_at", "");
    s.active     = j.value("active", true);
    return s;
  }
};

// ========== Utility ==========

inline std::string NowUTC() {
  char buf[32];
  time_t now = time(nullptr);
  struct tm tm_info;
  gmtime_r(&now, &tm_info);
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &tm_info);
  return buf;
}
