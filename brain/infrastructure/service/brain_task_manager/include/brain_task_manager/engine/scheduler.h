#pragma once
#include "brain_task_manager/core/types.h"
#include "brain_task_manager/core/logger.h"
#include "brain_task_manager/core/config_loader.h"
#include "brain_task_manager/ipc/ipc_client.h"
#include "brain_task_manager/store/task_store.h"
#include "brain_task_manager/store/spec_store.h"
#include <atomic>
#include <thread>
#include <vector>

// Scheduler: periodic scanning for deadlines, stale tasks/specs, heartbeat.
class Scheduler {
public:
  Scheduler(IpcClient& ipc, TaskStore& tasks, SpecStore& specs, const Config& cfg);

  // Start all timer threads.
  void Start();

  // Stop all timer threads.
  void Stop();

  bool IsRunning() const { return running_.load(); }

private:
  void HeartbeatLoop();
  void DeadlineLoop();
  void StaleTaskLoop();
  void StaleSpecLoop();

  // Parse ISO8601 string to time_t. Returns 0 on failure.
  time_t ParseISO8601(const std::string& s) const;

  IpcClient& ipc_;
  TaskStore& tasks_;
  SpecStore& specs_;
  const Config& cfg_;

  std::atomic<bool> running_{false};
  std::vector<std::thread> threads_;
};
