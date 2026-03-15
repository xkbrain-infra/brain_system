#pragma once
#include "brain_task_manager/core/types.h"
#include "brain_task_manager/core/logger.h"
#include <string>
#include <atomic>
#include <thread>
#include <functional>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

// NotifyListener: long-connection to notify socket for push-based events.
// Calls on_event callback when a message event arrives for this service.
class NotifyListener {
public:
  using EventCallback = std::function<void()>;

  NotifyListener(const std::string& socket_path,
                 const std::string& service_name,
                 EventCallback on_event);

  // Start listener thread.
  void Start();

  // Stop listener thread.
  void Stop();

  bool IsRunning() const { return running_.load(); }

private:
  void ListenLoop();

  std::string socket_path_;
  std::string service_name_;
  EventCallback on_event_;
  std::atomic<bool> running_{false};
  std::thread thread_;
};
