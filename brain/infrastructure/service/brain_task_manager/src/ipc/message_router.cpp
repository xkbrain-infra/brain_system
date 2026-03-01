#include "brain_task_manager/ipc/message_router.h"

MessageRouter::MessageRouter(IpcClient& ipc, TaskStore& tasks, SpecStore& specs,
                             ProjectDepStore& deps, DispatchGuard& guard, const Config& cfg)
  : ipc_(ipc), tasks_(tasks), specs_(specs), deps_(deps), guard_(guard), cfg_(cfg) {}

int MessageRouter::ProcessMessages() {
  auto msgs = ipc_.Recv(cfg_.recv_batch_size);
  if (msgs.empty()) return 0;

  std::vector<std::string> msg_ids;
  int processed = 0;

  for (auto& msg : msgs) {
    std::string msg_id = msg.value("msg_id", "");
    std::string from = msg.value("from", "");

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

    if (event_type == "TASK_CREATE") {
      response = HandleTaskCreate(payload, from);
    } else if (event_type == "TASK_UPDATE") {
      response = HandleTaskUpdate(payload, from);
    } else if (event_type == "TASK_QUERY") {
      response = HandleTaskQuery(payload);
    } else if (event_type == "TASK_DELETE") {
      response = HandleTaskDelete(payload);
    } else if (event_type == "TASK_STATS") {
      response = HandleTaskStats(payload);
    } else if (event_type == "TASK_PIPELINE_CHECK") {
      response = HandleTaskPipelineCheck(payload);
    } else if (event_type == "PROJECT_DEPENDENCY_SET") {
      response = HandleProjectDependencySet(payload);
    } else if (event_type == "PROJECT_DEPENDENCY_QUERY") {
      response = HandleProjectDependencyQuery(payload);
    } else if (event_type == "SPEC_CREATE") {
      response = HandleSpecCreate(payload);
    } else if (event_type == "SPEC_PROGRESS") {
      response = HandleSpecProgress(payload);
    } else if (event_type == "SPEC_QUERY") {
      response = HandleSpecQuery(payload);
    } else {
      LOG_WARN("router", LogFmt("unknown event_type: %s from %s", event_type.c_str(), from.c_str()));
      if (!msg_id.empty()) msg_ids.push_back(msg_id);
      continue;
    }

    // Fix-10: Send response with correlation fields so QA can match request<->response
    if (!from.empty() && !response.is_null()) {
      if (!msg_id.empty()) {
        response["request_msg_id"] = msg_id;
      }
      std::string conv_id = msg.value("conversation_id", "");
      ipc_.Send(from, response, "response", conv_id);
    }

    if (!msg_id.empty()) msg_ids.push_back(msg_id);
    processed++;
  }

  // ACK all processed messages
  if (!msg_ids.empty()) {
    ipc_.Ack(msg_ids);
  }

  return processed;
}

// ========== Task Handlers ==========

json MessageRouter::HandleTaskCreate(const json& payload, const std::string& /*from*/) {
  Task t;
  t.task_id     = payload.value("task_id", "");
  t.title       = payload.value("title", "");
  t.owner       = payload.value("owner", "");
  t.priority    = payload.value("priority", "normal");
  t.spec_id     = payload.value("spec_id", "");
  t.group       = payload.value("group", "");
  t.description = payload.value("description", "");
  t.deadline    = payload.value("deadline", "");

  if (payload.contains("depends_on") && payload["depends_on"].is_array()) {
    for (auto& d : payload["depends_on"]) {
      if (d.is_string()) t.depends_on.push_back(d.get<std::string>());
    }
  }
  if (payload.contains("tags") && payload["tags"].is_array()) {
    for (auto& tag : payload["tags"]) {
      if (tag.is_string()) t.tags.push_back(tag.get<std::string>());
    }
  }

  // Fix-1: check owner agent is online (if configured)
  if (cfg_.check_owner_online && !t.owner.empty()) {
    auto agents = ipc_.ListAgents(false);
    bool found = false;
    if (agents.is_array()) {
      for (auto& a : agents) {
        std::string agent_name = a.value("agent_name", "");
        if (agent_name.empty()) agent_name = a.value("name", "");
        if (agent_name == t.owner) {
          found = true;
          break;
        }
      }
    }
    if (!found) {
      return json{
        {"event_type", "TASK_REJECTED"},
        {"status", "error"},
        {"error", "owner agent not online: " + t.owner}
      };
    }
  }

  std::string err = tasks_.Create(t);
  if (!err.empty()) {
    return json{{"event_type", "TASK_REJECTED"}, {"status", "error"}, {"error", err}};
  }

  PersistAll();

  const Task* created = tasks_.Get(t.task_id);
  return json{
    {"event_type", "TASK_CREATED"},
    {"status", "ok"},
    {"task_id", t.task_id},
    {"created_at", created ? created->created_at : NowUTC()}
  };
}

// Fix-11c: dispatch guard only applies for pending->in_progress when spec is registered
json MessageRouter::HandleTaskUpdate(const json& payload, const std::string& /*from*/) {
  std::string task_id = payload.value("task_id", "");
  if (task_id.empty()) {
    return json{{"event_type", "TASK_REJECTED"}, {"status", "error"}, {"error", "task_id is required"}};
  }

  // Dispatch guard: only for pending -> in_progress AND only if spec is formally registered
  if (payload.contains("status") && payload["status"].is_string()
      && payload["status"].get<std::string>() == "in_progress") {
    const Task* t = tasks_.Get(task_id);
    if (t && t->status == TaskStatus::Pending && !t->spec_id.empty()) {
      // Only enforce guard if spec is registered in spec_store
      const SpecRecord* spec = specs_.Get(t->spec_id);
      if (spec) {
        auto guard_result = guard_.Check(t->spec_id);
        if (!guard_result.pass) {
          return json{
            {"event_type", "TASK_REJECTED"},
            {"status", "error"},
            {"error", "dispatch guard check failed"},
            {"missing", guard_result.missing}
          };
        }
      }
    }
  }

  // Build update fields (exclude event_type and task_id)
  json fields = payload;
  fields.erase("event_type");
  fields.erase("task_id");

  std::string err = tasks_.Update(task_id, fields);
  if (!err.empty()) {
    return json{{"event_type", "TASK_REJECTED"}, {"status", "error"}, {"error", err}};
  }

  PersistAll();

  return json{
    {"event_type", "TASK_UPDATED"},
    {"status", "ok"},
    {"task_id", task_id},
    {"updated_at", NowUTC()}
  };
}

// Fix-5: validate filter fields before querying
json MessageRouter::HandleTaskQuery(const json& payload) {
  // Validate status filter if provided
  std::string status_filter = payload.value("status", "");
  if (!status_filter.empty() && !IsValidStatus(status_filter)) {
    return json{
      {"event_type", "TASK_QUERY_ERROR"},
      {"status", "error"},
      {"error", "invalid status filter: " + status_filter}
    };
  }

  TaskQueryFilter filter;
  filter.task_id = payload.value("task_id", "");
  filter.spec_id = payload.value("spec_id", "");
  filter.status  = status_filter;
  filter.group   = payload.value("group", "");
  filter.owner   = payload.value("owner", "");

  auto results = tasks_.Query(filter);

  json tasks_json = json::array();
  for (auto& t : results) {
    tasks_json.push_back(t.to_json());
  }

  return json{
    {"event_type", "TASK_QUERY_RESULT"},
    {"status", "ok"},
    {"tasks", tasks_json},
    {"count", static_cast<int>(results.size())}
  };
}

json MessageRouter::HandleTaskDelete(const json& payload) {
  std::string task_id = payload.value("task_id", "");
  if (task_id.empty()) {
    return json{{"event_type", "TASK_NOT_FOUND"}, {"status", "error"}, {"error", "task_id is required"}};
  }

  std::string err = tasks_.Delete(task_id);
  if (!err.empty()) {
    return json{{"event_type", "TASK_NOT_FOUND"}, {"status", "error"}, {"error", err}};
  }

  PersistAll();

  return json{
    {"event_type", "TASK_DELETED"},
    {"status", "ok"},
    {"task_id", task_id}
  };
}

// Fix-11a: spec_id is a task label, not a spec object reference. Only reject if empty.
json MessageRouter::HandleTaskStats(const json& payload) {
  std::string spec_id = payload.value("spec_id", "");
  if (spec_id.empty()) {
    return json{{"event_type", "SPEC_NOT_FOUND"}, {"status", "error"}, {"error", "spec_id is required"}};
  }

  auto stats = tasks_.Stats(spec_id);

  // Fix-12a: no tasks for this spec_id means spec not found
  if (stats.total == 0) {
    return json{{"event_type", "SPEC_NOT_FOUND"}, {"status", "error"}, {"error", "spec not found: " + spec_id}};
  }

  // Update dispatch guard
  guard_.MarkStatsChecked(spec_id, stats.total);
  guard_.Save();

  return json{
    {"event_type", "TASK_STATS_RESULT"},
    {"status", "ok"},
    {"spec_id", spec_id},
    {"total", stats.total},
    {"by_status", stats.by_status},
    {"by_priority", stats.by_priority}
  };
}

// Fix-11b: spec_id is a task label, not a spec object reference. Only reject if empty.
json MessageRouter::HandleTaskPipelineCheck(const json& payload) {
  std::string spec_id = payload.value("spec_id", "");
  if (spec_id.empty()) {
    return json{{"event_type", "PIPELINE_CHECK_ERROR"}, {"status", "error"}, {"error", "spec_id is required"}};
  }

  auto result = tasks_.PipelineCheck(spec_id);

  // Fix-12b: no tasks for this spec_id means spec not found
  if (result.total_tasks == 0) {
    return json{{"event_type", "PIPELINE_CHECK_ERROR"}, {"status", "error"}, {"error", "spec not found: " + spec_id}};
  }

  // Update dispatch guard
  guard_.MarkPipelineValid(spec_id, result.valid);
  guard_.Save();

  return json{
    {"event_type", "TASK_PIPELINE_RESULT"},
    {"status", "ok"},
    {"valid", result.valid},
    {"total_tasks", result.total_tasks},
    {"edges", result.edges},
    {"ready_tasks", result.ready_tasks},
    {"blocked_tasks", result.blocked_tasks},
    {"cycle_detected", result.cycle_detected},
    {"cycle_path", result.cycle_path},
    {"missing_dependencies", result.missing_dependencies},
    {"flow_violations", result.flow_violations}
  };
}

// ========== Project Dependency Handlers ==========

json MessageRouter::HandleProjectDependencySet(const json& payload) {
  std::string project_id = payload.value("project_id", "");
  if (project_id.empty()) {
    return json{{"event_type", "CYCLE_DETECTED"}, {"status", "error"}, {"error", "project_id is required"}};
  }

  std::vector<std::string> depends_on;
  if (payload.contains("depends_on") && payload["depends_on"].is_array()) {
    for (auto& d : payload["depends_on"]) {
      if (d.is_string()) depends_on.push_back(d.get<std::string>());
    }
  }

  std::string err = deps_.Set(project_id, depends_on);
  if (!err.empty()) {
    return json{{"event_type", "CYCLE_DETECTED"}, {"status", "error"}, {"error", err}};
  }

  // Update dispatch guard for all specs matching this project
  guard_.MarkDepsSet(project_id);

  deps_.Save();
  guard_.Save();

  return json{
    {"event_type", "PROJECT_DEPENDENCY_UPDATED"},
    {"status", "ok"},
    {"project_id", project_id}
  };
}

// Fix-4: check project existence before querying dependencies
json MessageRouter::HandleProjectDependencyQuery(const json& payload) {
  std::string project_id = payload.value("project_id", "");
  if (project_id.empty()) {
    return json{{"event_type", "PROJECT_NOT_FOUND"}, {"status", "error"}, {"error", "project_id is required"}};
  }

  auto upstream = deps_.GetDependencies(project_id);
  auto downstream = deps_.GetDownstream(project_id);

  // If project has no deps registered AND no projects depend on it, it's not found
  if (!deps_.HasDeps(project_id) && downstream.empty()) {
    return json{{"event_type", "PROJECT_NOT_FOUND"}, {"status", "error"}, {"error", "project not found: " + project_id}};
  }

  return json{
    {"event_type", "PROJECT_DEPENDENCY_RESULT"},
    {"status", "ok"},
    {"project_id", project_id},
    {"depends_on", upstream},
    {"downstream", downstream}
  };
}

// ========== Spec Handlers ==========

json MessageRouter::HandleSpecCreate(const json& payload) {
  SpecRecord s;
  s.spec_id = payload.value("spec_id", "");
  s.title   = payload.value("title", "");
  s.group   = payload.value("group", "");
  s.owner   = payload.value("owner", "");

  std::string err;
  std::string intake_task_id = specs_.Create(s, err);
  if (!err.empty()) {
    return json{{"event_type", "SPEC_REJECTED"}, {"status", "error"}, {"error", err}};
  }

  // Create intake task automatically
  Task intake;
  intake.task_id     = intake_task_id;
  intake.title       = "Kickoff: " + s.title;
  intake.owner       = s.owner;
  intake.priority    = "high";
  intake.spec_id     = s.spec_id;
  intake.group       = s.group;
  intake.description = "Spec intake baseline task. Refine 06_tasks.yaml and keep task list synchronized in task_manager.";
  intake.tags        = {"project-intake", "tasklist-required"};

  std::string task_err = tasks_.Create(intake);
  if (!task_err.empty()) {
    LOG_WARN("router", LogFmt("failed to create intake task: %s", task_err.c_str()));
  }

  PersistAll();

  return json{
    {"event_type", "SPEC_CREATED"},
    {"status", "ok"},
    {"spec_id", s.spec_id},
    {"intake_task_id", intake_task_id}
  };
}

json MessageRouter::HandleSpecProgress(const json& payload) {
  std::string spec_id = payload.value("spec_id", "");
  std::string target_stage = payload.value("target_stage", "");

  if (spec_id.empty() || target_stage.empty()) {
    return json{{"event_type", "SPEC_PROGRESS_REJECTED"}, {"status", "error"},
                {"error", "spec_id and target_stage are required"}};
  }

  std::string err = specs_.Progress(spec_id, target_stage);
  if (!err.empty()) {
    return json{{"event_type", "SPEC_PROGRESS_REJECTED"}, {"status", "error"}, {"error", err}};
  }

  PersistAll();

  return json{
    {"event_type", "SPEC_PROGRESSED"},
    {"status", "ok"},
    {"spec_id", spec_id},
    {"to_stage", target_stage}
  };
}

// Fix-6: validate filter fields before querying specs
json MessageRouter::HandleSpecQuery(const json& payload) {
  // Validate stage filter if provided
  std::string stage_filter = payload.value("stage", "");
  if (!stage_filter.empty() && !IsValidStage(stage_filter)) {
    return json{
      {"event_type", "SPEC_QUERY_ERROR"},
      {"status", "error"},
      {"error", "invalid stage filter: " + stage_filter}
    };
  }

  SpecQueryFilter filter;
  filter.spec_id = payload.value("spec_id", "");
  filter.group   = payload.value("group", "");
  filter.stage   = stage_filter;

  auto results = specs_.Query(filter);

  json specs_json = json::array();
  for (auto& s : results) {
    specs_json.push_back(s.to_json());
  }

  return json{
    {"event_type", "SPEC_QUERY_RESULT"},
    {"status", "ok"},
    {"specs", specs_json},
    {"count", static_cast<int>(results.size())}
  };
}

void MessageRouter::PersistAll() {
  if (!tasks_.Save()) LOG_ERROR("router", "failed to persist tasks");
  if (!specs_.Save()) LOG_ERROR("router", "failed to persist specs");
}
