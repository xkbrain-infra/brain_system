#pragma once
#include "brain_task_manager/core/types.h"
#include "brain_task_manager/core/logger.h"
#include "brain_task_manager/ipc/ipc_client.h"
#include "brain_task_manager/store/task_store.h"
#include "brain_task_manager/store/spec_store.h"
#include <string>
#include <atomic>
#include <thread>
#include <ctime>

// HealthServer: HTTP GET /health endpoint.
class HealthServer {
public:
  HealthServer(int port, const std::string& service_name,
               IpcClient& ipc, TaskStore& tasks, SpecStore& specs);

  // Start HTTP server thread.
  void Start();

  // Stop HTTP server.
  void Stop();

  bool IsRunning() const { return running_.load(); }

private:
  void ServerLoop();

  int port_;
  std::string service_name_;
  IpcClient& ipc_;
  TaskStore& tasks_;
  SpecStore& specs_;
  time_t start_time_;

  std::atomic<bool> running_{false};
  std::thread thread_;
};
