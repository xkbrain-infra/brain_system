#pragma once
#include "brain_task_manager/core/types.h"
#include "brain_task_manager/core/logger.h"
#include <string>
#include <vector>
#include <optional>
#include <mutex>
#include <atomic>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

class IpcClient {
public:
  explicit IpcClient(const std::string& socket_path, const std::string& service_name)
    : socket_path_(socket_path), service_name_(service_name) {}

  // Connect to daemon and register service. Returns true on success.
  bool Connect();

  // Send heartbeat. Returns true on success.
  bool Heartbeat();

  // Send IPC message. Returns msg_id on success.
  std::optional<std::string> Send(const std::string& to, const json& payload,
                                   const std::string& message_type = "response",
                                   const std::string& conversation_id = "");

  // Receive pending messages. Returns list of raw message JSON objects.
  std::vector<json> Recv(int max_items = 10);

  // Acknowledge messages. Returns number acked.
  int Ack(const std::vector<std::string>& msg_ids);

  // List online agents. Returns array of agent info.
  json ListAgents(bool include_offline = false);

  // Raw request to daemon. Thread-safe.
  std::optional<json> Request(const json& req);

  bool IsConnected() const { return connected_.load(); }

private:
  std::optional<json> DoRequest(const json& req);

  std::string socket_path_;
  std::string service_name_;
  std::atomic<bool> connected_{false};
  std::mutex mu_;
};
