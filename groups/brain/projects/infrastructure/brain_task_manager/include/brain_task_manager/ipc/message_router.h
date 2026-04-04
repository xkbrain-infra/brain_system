#pragma once
#include "brain_task_manager/core/types.h"
#include "brain_task_manager/core/logger.h"
#include "brain_task_manager/core/config_loader.h"
#include "brain_task_manager/ipc/ipc_client.h"
#include "brain_task_manager/store/task_store.h"
#include "brain_task_manager/store/spec_store.h"
#include "brain_task_manager/store/event_store.h"
#include "brain_task_manager/store/project_dep_store.h"
#include "brain_task_manager/engine/dispatch_guard.h"
#include <string>

class MessageRouter {
public:
  MessageRouter(IpcClient& ipc, TaskStore& tasks, ProjectStore& projects,
                EventStore& events, ProjectDepStore& deps,
                DispatchGuard& guard, const Config& cfg);

  // 处理待收消息：recv → route → ack → respond。返回处理消息数。
  int ProcessMessages();

private:
  // Task 操作
  json HandleTaskCreate(const json& payload, const std::string& from);
  json HandleTaskUpdate(const json& payload, const std::string& from);
  json HandleTaskQuery(const json& payload);
  json HandleTaskDelete(const json& payload);
  json HandleTaskStats(const json& payload);
  json HandleTaskPipelineCheck(const json& payload);

  // Project 操作（原 Spec）
  json HandleProjectCreate(const json& payload);
  json HandleProjectProgress(const json& payload);
  json HandleProjectQuery(const json& payload);

  // Project 依赖
  json HandleProjectDependencySet(const json& payload);
  json HandleProjectDependencyQuery(const json& payload);

  // 辅助
  void AppendEvent(const std::string& event_type, const Task& task,
                   const std::string& actor, const std::string& note = "");
  void PersistAll();

  IpcClient&      ipc_;
  TaskStore&      tasks_;
  ProjectStore&   projects_;
  EventStore&     events_;
  ProjectDepStore& deps_;
  DispatchGuard&  guard_;
  const Config&   cfg_;
};
