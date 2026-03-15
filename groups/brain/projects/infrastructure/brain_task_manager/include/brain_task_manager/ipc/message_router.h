#pragma once
#include "brain_task_manager/core/types.h"
#include "brain_task_manager/core/logger.h"
#include "brain_task_manager/core/config_loader.h"
#include "brain_task_manager/ipc/ipc_client.h"
#include "brain_task_manager/store/task_store.h"
#include "brain_task_manager/store/spec_store.h"
#include "brain_task_manager/store/project_dep_store.h"
#include "brain_task_manager/engine/dispatch_guard.h"
#include <string>
#include <functional>

// MessageRouter: receives IPC messages, routes by event_type, sends responses.
class MessageRouter {
public:
  MessageRouter(IpcClient& ipc, TaskStore& tasks, SpecStore& specs,
                ProjectDepStore& deps, DispatchGuard& guard, const Config& cfg);

  // Process pending messages: recv -> route -> ack -> respond.
  // Returns number of messages processed.
  int ProcessMessages();

private:
  // Handler for each event_type. Returns response payload JSON.
  json HandleTaskCreate(const json& payload, const std::string& from);
  json HandleTaskUpdate(const json& payload, const std::string& from);
  json HandleTaskQuery(const json& payload);
  json HandleTaskDelete(const json& payload);
  json HandleTaskStats(const json& payload);
  json HandleTaskPipelineCheck(const json& payload);
  json HandleProjectDependencySet(const json& payload);
  json HandleProjectDependencyQuery(const json& payload);
  json HandleSpecCreate(const json& payload);
  json HandleSpecProgress(const json& payload);
  json HandleSpecQuery(const json& payload);

  // Save all stores after mutation.
  void PersistAll();

  IpcClient& ipc_;
  TaskStore& tasks_;
  SpecStore& specs_;
  ProjectDepStore& deps_;
  DispatchGuard& guard_;
  const Config& cfg_;
};
