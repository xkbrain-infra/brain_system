#include "brain_task_manager/ipc/message_router.h"

MessageRouter::MessageRouter(IpcClient& ipc, TaskStore& tasks, ProjectStore& projects,
                             EventStore& events, ProjectDepStore& deps,
                             DispatchGuard& guard, const Config& cfg)
  : ipc_(ipc), tasks_(tasks), projects_(projects), events_(events),
    deps_(deps), guard_(guard), cfg_(cfg) {}

int MessageRouter::ProcessMessages() {
  auto msgs = ipc_.Recv(cfg_.recv_batch_size);
  if (msgs.empty()) return 0;

  std::vector<std::string> msg_ids;
  int processed = 0;

  for (auto& msg : msgs) {
    std::string msg_id;
    if (msg.contains("msg_id") && msg["msg_id"].is_string())
      msg_id = msg["msg_id"].get<std::string>();
    std::string from;
    if (msg.contains("from") && msg["from"].is_string())
      from = msg["from"].get<std::string>();

    json payload;
    if (msg.contains("payload") && msg["payload"].is_object()) {
      payload = msg["payload"];
    } else if (msg.contains("payload") && msg["payload"].is_string()) {
      payload = json::parse(msg["payload"].get<std::string>(), nullptr, false);
      if (payload.is_discarded()) {
        LOG_WARN("router", LogFmt("failed to parse payload from %s", from.c_str()));
        if (!msg_id.empty()) msg_ids.push_back(msg_id);
        continue;
      }
    } else {
      LOG_WARN("router", LogFmt("missing payload from %s", from.c_str()));
      if (!msg_id.empty()) msg_ids.push_back(msg_id);
      continue;
    }

    std::string event_type = payload.value("event_type", "");
    LOG_INFO("router", LogFmt("processing %s from %s (msg_id=%s)",
             event_type.c_str(), from.c_str(), msg_id.c_str()));

    json response;

    if      (event_type == "TASK_CREATE")             response = HandleTaskCreate(payload, from);
    else if (event_type == "TASK_UPDATE")             response = HandleTaskUpdate(payload, from);
    else if (event_type == "TASK_QUERY")              response = HandleTaskQuery(payload);
    else if (event_type == "TASK_DELETE")             response = HandleTaskDelete(payload);
    else if (event_type == "TASK_STATS")              response = HandleTaskStats(payload);
    else if (event_type == "TASK_PIPELINE_CHECK")     response = HandleTaskPipelineCheck(payload);
    else if (event_type == "PROJECT_CREATE")          response = HandleProjectCreate(payload);
    else if (event_type == "PROJECT_PROGRESS")        response = HandleProjectProgress(payload);
    else if (event_type == "PROJECT_QUERY")           response = HandleProjectQuery(payload);
    else if (event_type == "PROJECT_DEPENDENCY_SET")  response = HandleProjectDependencySet(payload);
    else if (event_type == "PROJECT_DEPENDENCY_QUERY")response = HandleProjectDependencyQuery(payload);
    else {
      LOG_WARN("router", LogFmt("unknown event_type: %s from %s",
               event_type.c_str(), from.c_str()));
      if (!msg_id.empty()) msg_ids.push_back(msg_id);
      continue;
    }

    if (!from.empty() && !response.is_null()) {
      if (!msg_id.empty()) response["request_msg_id"] = msg_id;
      std::string conv_id;
      if (msg.contains("conversation_id") && msg["conversation_id"].is_string())
        conv_id = msg["conversation_id"].get<std::string>();
      ipc_.Send(from, response, "response", conv_id);
    }

    if (!msg_id.empty()) msg_ids.push_back(msg_id);
    processed++;
  }

  if (!msg_ids.empty()) ipc_.Ack(msg_ids);
  return processed;
}

// ========== 辅助 ==========

void MessageRouter::AppendEvent(const std::string& event_type, const Task& task,
                                 const std::string& actor, const std::string& note) {
  TaskEvent e;
  e.event_type = event_type;
  e.task_id    = task.task_id;
  e.project_id = task.project_id;
  e.group      = task.group;
  e.actor      = actor;
  e.timestamp  = NowUTC();
  e.note       = note;
  events_.Append(e);
}

void MessageRouter::PersistAll() {
  if (!tasks_.Save()) LOG_ERROR("router", "failed to persist tasks");
  if (!projects_.Save()) LOG_ERROR("router", "failed to persist projects");
}

// ========== Task 操作 ==========

json MessageRouter::HandleTaskCreate(const json& payload, const std::string& from) {
  Task t;
  t.task_id         = payload.value("task_id", "");
  t.project_id      = payload.value("project_id", "");
  t.group           = payload.value("group", "");
  t.title           = payload.value("title", "");
  t.owner           = payload.value("owner", "");
  t.priority        = payload.value("priority", "normal");
  t.description     = payload.value("description", "");
  t.deadline        = payload.value("deadline", "");
  t.trigger_policy  = payload.value("trigger_policy", "manual");
  t.review_by       = payload.value("review_by", "");
  t.escalation_policy = payload.value("escalation_policy", "");
  t.next_check_at   = payload.value("next_check_at", "");

  if (payload.contains("participants") && payload["participants"].is_array())
    for (auto& p : payload["participants"])
      if (p.is_string()) t.participants.push_back(p.get<std::string>());
  if (payload.contains("depends_on") && payload["depends_on"].is_array())
    for (auto& d : payload["depends_on"])
      if (d.is_string()) t.depends_on.push_back(d.get<std::string>());
  if (payload.contains("todo_list") && payload["todo_list"].is_array())
    for (auto& item : payload["todo_list"])
      t.todo_list.push_back(TodoItem::from_json(item));
  if (payload.contains("tags") && payload["tags"].is_array())
    for (auto& tag : payload["tags"])
      if (tag.is_string()) t.tags.push_back(tag.get<std::string>());

  // 可选：校验 owner agent 在线
  if (cfg_.check_owner_online && !t.owner.empty()) {
    auto agents = ipc_.ListAgents(false);
    bool found = false;
    if (agents.is_array()) {
      for (auto& a : agents) {
        std::string agent_name = a.value("agent_name", "");
        if (agent_name.empty()) agent_name = a.value("name", "");
        if (agent_name == t.owner) { found = true; break; }
      }
    }
    if (!found) {
      return json{{"event_type", "TASK_REJECTED"}, {"status", "error"},
                  {"error", "owner agent not online: " + t.owner}};
    }
  }

  std::string err = tasks_.Create(t);
  if (!err.empty())
    return json{{"event_type", "TASK_REJECTED"}, {"status", "error"}, {"error", err}};

  // 持久化 + 记录事件
  tasks_.Save();
  auto created = tasks_.Get(t.task_id);
  if (created) AppendEvent("task.created", *created, from);

  return json{
    {"event_type", "TASK_CREATED"}, {"status", "ok"},
    {"task_id",    t.task_id},
    {"created_at", created ? created->created_at : NowUTC()}
  };
}

json MessageRouter::HandleTaskUpdate(const json& payload, const std::string& from) {
  std::string task_id = payload.value("task_id", "");
  if (task_id.empty())
    return json{{"event_type", "TASK_REJECTED"}, {"status", "error"},
                {"error", "task_id is required"}};

  // Dispatch guard：pending→in_progress 且 project 已注册时生效
  if (payload.contains("status") && payload["status"].is_string()
      && payload["status"].get<std::string>() == "in_progress") {
    auto t_opt = tasks_.Get(task_id);
    if (t_opt && t_opt->status == TaskStatus::Pending && !t_opt->project_id.empty()) {
      if (projects_.Get(t_opt->project_id)) {
        auto guard_result = guard_.Check(t_opt->project_id);
        if (!guard_result.pass) {
          return json{
            {"event_type", "TASK_REJECTED"}, {"status", "error"},
            {"error", "dispatch guard check failed"}, {"missing", guard_result.missing}
          };
        }
      }
    }
  }

  json fields = payload;
  fields.erase("event_type");
  fields.erase("task_id");

  int64_t expected_version = -1;
  if (payload.contains("expected_version")) {
    expected_version = payload["expected_version"].get<int64_t>();
    fields.erase("expected_version");
  }

  // 记录更新前的状态，用于事件类型判断
  auto before = tasks_.Get(task_id);
  TaskStatus old_status = before ? before->status : TaskStatus::Pending;

  std::string err = tasks_.Update(task_id, fields, expected_version);
  if (!err.empty())
    return json{{"event_type", "TASK_REJECTED"}, {"status", "error"}, {"error", err}};

  tasks_.Save();

  auto updated = tasks_.Get(task_id);
  uint64_t new_version = updated ? updated->version : 0;

  // 根据状态变化写入对应事件
  if (updated && payload.contains("status") && payload["status"].is_string()) {
    TaskStatus new_status = updated->status;
    std::string actor = from;
    std::string note  = payload.value("note", "");

    std::string evt;
    if      (new_status == TaskStatus::InProgress && old_status == TaskStatus::Ready)
      evt = "task.active";
    else if (new_status == TaskStatus::InProgress && old_status == TaskStatus::Pending)
      evt = "task.active";
    else if (new_status == TaskStatus::InProgress)  // rework
      evt = "task.active";
    else if (new_status == TaskStatus::Review)      evt = "task.review_requested";
    else if (new_status == TaskStatus::Verified)    evt = "task.verified";
    else if (new_status == TaskStatus::Completed)   evt = "task.done";
    else if (new_status == TaskStatus::Failed)      evt = "task.failed";
    else if (new_status == TaskStatus::Cancelled)   evt = "task.cancelled";
    else if (new_status == TaskStatus::Blocked)     evt = "task.blocked";
    else if (new_status == TaskStatus::Ready && old_status == TaskStatus::Blocked)
      evt = "task.unblocked";
    else if (new_status == TaskStatus::Archived)    evt = "task.archived";

    if (!evt.empty()) AppendEvent(evt, *updated, actor, note);
  }

  return json{
    {"event_type", "TASK_UPDATED"}, {"status", "ok"},
    {"task_id",    task_id},
    {"version",    new_version},
    {"updated_at", NowUTC()}
  };
}

json MessageRouter::HandleTaskQuery(const json& payload) {
  std::string status_filter = payload.value("status", "");
  if (!status_filter.empty() && !IsValidStatus(status_filter)) {
    return json{{"event_type", "TASK_QUERY_ERROR"}, {"status", "error"},
                {"error", "invalid status filter: " + status_filter}};
  }

  TaskQueryFilter filter;
  filter.task_id    = payload.value("task_id", "");
  filter.project_id = payload.value("project_id", "");
  filter.status     = status_filter;
  filter.group      = payload.value("group", "");
  filter.owner      = payload.value("owner", "");

  auto results = tasks_.Query(filter);
  json tasks_json = json::array();
  for (auto& t : results) tasks_json.push_back(t.to_json());

  return json{
    {"event_type", "TASK_QUERY_RESULT"}, {"status", "ok"},
    {"tasks", tasks_json}, {"count", (int)results.size()}
  };
}

json MessageRouter::HandleTaskDelete(const json& payload) {
  std::string task_id = payload.value("task_id", "");
  if (task_id.empty())
    return json{{"event_type", "TASK_NOT_FOUND"}, {"status", "error"},
                {"error", "task_id is required"}};

  std::string err = tasks_.Delete(task_id);
  if (!err.empty())
    return json{{"event_type", "TASK_NOT_FOUND"}, {"status", "error"}, {"error", err}};

  tasks_.Save();
  return json{{"event_type", "TASK_DELETED"}, {"status", "ok"}, {"task_id", task_id}};
}

json MessageRouter::HandleTaskStats(const json& payload) {
  std::string project_id = payload.value("project_id", "");
  if (project_id.empty())
    return json{{"event_type", "PROJECT_NOT_FOUND"}, {"status", "error"},
                {"error", "project_id is required"}};

  auto stats = tasks_.Stats(project_id);
  if (stats.total == 0)
    return json{{"event_type", "PROJECT_NOT_FOUND"}, {"status", "error"},
                {"error", "no tasks found for project: " + project_id}};

  guard_.MarkStatsChecked(project_id, stats.total);
  guard_.Save();

  return json{
    {"event_type",   "TASK_STATS_RESULT"}, {"status", "ok"},
    {"project_id",   project_id},
    {"total",        stats.total},
    {"by_status",    stats.by_status},
    {"by_priority",  stats.by_priority}
  };
}

json MessageRouter::HandleTaskPipelineCheck(const json& payload) {
  std::string project_id = payload.value("project_id", "");
  if (project_id.empty())
    return json{{"event_type", "PIPELINE_CHECK_ERROR"}, {"status", "error"},
                {"error", "project_id is required"}};

  auto result = tasks_.PipelineCheck(project_id);
  if (result.total_tasks == 0)
    return json{{"event_type", "PIPELINE_CHECK_ERROR"}, {"status", "error"},
                {"error", "no tasks found for project: " + project_id}};

  guard_.MarkPipelineValid(project_id, result.valid);
  guard_.Save();

  return json{
    {"event_type",          "TASK_PIPELINE_RESULT"}, {"status", "ok"},
    {"valid",               result.valid},
    {"total_tasks",         result.total_tasks},
    {"edges",               result.edges},
    {"ready_tasks",         result.ready_tasks},
    {"blocked_tasks",       result.blocked_tasks},
    {"cycle_detected",      result.cycle_detected},
    {"cycle_path",          result.cycle_path},
    {"missing_dependencies",result.missing_dependencies},
    {"flow_violations",     result.flow_violations}
  };
}

// ========== Project 操作 ==========

json MessageRouter::HandleProjectCreate(const json& payload) {
  ProjectRecord p;
  p.project_id = payload.value("project_id", "");
  p.title      = payload.value("title", "");
  p.group      = payload.value("group", "");
  p.owner      = payload.value("owner", "");

  std::string err;
  std::string intake_task_id = projects_.Create(p, err);
  if (!err.empty())
    return json{{"event_type", "PROJECT_REJECTED"}, {"status", "error"}, {"error", err}};

  // 自动创建 intake task
  Task intake;
  intake.task_id      = intake_task_id;
  intake.project_id   = p.project_id;
  intake.group        = p.group;
  intake.title        = "Kickoff: " + p.title;
  intake.owner        = p.owner;
  intake.priority     = "high";
  intake.trigger_policy = "manual";
  intake.description  = "Project intake baseline task. 完成 06_tasks.yaml 任务清单拆解并同步到 task_manager。";
  intake.tags         = {"project-intake", "tasklist-required"};

  std::string task_err = tasks_.Create(intake);
  if (!task_err.empty())
    LOG_WARN("router", LogFmt("failed to create intake task: %s", task_err.c_str()));
  else {
    auto created = tasks_.Get(intake_task_id);
    if (created) AppendEvent("task.created", *created, p.owner, "project intake");
  }

  tasks_.Save();

  return json{
    {"event_type",     "PROJECT_CREATED"}, {"status", "ok"},
    {"project_id",     p.project_id},
    {"intake_task_id", intake_task_id}
  };
}

json MessageRouter::HandleProjectProgress(const json& payload) {
  std::string project_id   = payload.value("project_id", "");
  std::string target_stage = payload.value("target_stage", "");

  if (project_id.empty() || target_stage.empty())
    return json{{"event_type", "PROJECT_PROGRESS_REJECTED"}, {"status", "error"},
                {"error", "project_id and target_stage are required"}};

  std::string err = projects_.Progress(project_id, target_stage);
  if (!err.empty())
    return json{{"event_type", "PROJECT_PROGRESS_REJECTED"}, {"status", "error"},
                {"error", err}};

  return json{
    {"event_type",  "PROJECT_PROGRESSED"}, {"status", "ok"},
    {"project_id",  project_id},
    {"to_stage",    target_stage}
  };
}

json MessageRouter::HandleProjectQuery(const json& payload) {
  std::string stage_filter = payload.value("stage", "");
  if (!stage_filter.empty() && !IsValidStage(stage_filter)) {
    return json{{"event_type", "PROJECT_QUERY_ERROR"}, {"status", "error"},
                {"error", "invalid stage filter: " + stage_filter}};
  }

  ProjectQueryFilter filter;
  filter.project_id = payload.value("project_id", "");
  filter.group      = payload.value("group", "");
  filter.stage      = stage_filter;

  auto results = projects_.Query(filter);
  json projects_json = json::array();
  for (auto& proj : results) projects_json.push_back(proj.to_json());

  return json{
    {"event_type", "PROJECT_QUERY_RESULT"}, {"status", "ok"},
    {"projects", projects_json}, {"count", (int)results.size()}
  };
}

// ========== Project 依赖 ==========

json MessageRouter::HandleProjectDependencySet(const json& payload) {
  std::string project_id = payload.value("project_id", "");
  if (project_id.empty())
    return json{{"event_type", "CYCLE_DETECTED"}, {"status", "error"},
                {"error", "project_id is required"}};

  std::vector<std::string> depends_on;
  if (payload.contains("depends_on") && payload["depends_on"].is_array())
    for (auto& d : payload["depends_on"])
      if (d.is_string()) depends_on.push_back(d.get<std::string>());

  std::string err = deps_.Set(project_id, depends_on);
  if (!err.empty())
    return json{{"event_type", "CYCLE_DETECTED"}, {"status", "error"}, {"error", err}};

  guard_.MarkDepsSet(project_id);
  deps_.Save();
  guard_.Save();

  return json{
    {"event_type", "PROJECT_DEPENDENCY_UPDATED"}, {"status", "ok"},
    {"project_id", project_id}
  };
}

json MessageRouter::HandleProjectDependencyQuery(const json& payload) {
  std::string project_id = payload.value("project_id", "");
  if (project_id.empty())
    return json{{"event_type", "PROJECT_NOT_FOUND"}, {"status", "error"},
                {"error", "project_id is required"}};

  auto upstream   = deps_.GetDependencies(project_id);
  auto downstream = deps_.GetDownstream(project_id);

  if (!deps_.HasDeps(project_id) && downstream.empty())
    return json{{"event_type", "PROJECT_NOT_FOUND"}, {"status", "error"},
                {"error", "project not found: " + project_id}};

  return json{
    {"event_type",  "PROJECT_DEPENDENCY_RESULT"}, {"status", "ok"},
    {"project_id",  project_id},
    {"depends_on",  upstream},
    {"downstream",  downstream}
  };
}
