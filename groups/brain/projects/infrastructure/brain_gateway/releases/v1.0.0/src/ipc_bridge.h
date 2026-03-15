#pragma once
// IPC Bridge: per-request Unix socket connection to brain_ipc daemon.
// brain_ipc is a one-request-per-connection protocol (like daemon_client.py).
// Connect() registers the service; each subsequent Request() opens a fresh
// connection, sends one JSON action, reads one JSON response, then closes.

#include "config.h"
#include <json.hpp>
#include <optional>
#include <string>
#include <vector>

struct IpcMessage {
  std::string msg_id;
  std::string from;
  std::string to;
  nlohmann::json payload;
  std::string message_type;
};

class IpcBridge {
 public:
  explicit IpcBridge(const IpcConfig& cfg, std::string service_name);
  ~IpcBridge();

  // Register service with brain_ipc daemon. Returns false if daemon unreachable.
  bool Connect();

  // Mark as disconnected (no socket to close)
  void Disconnect();

  bool IsConnected() const { return connected_; }

  // Send a message via IPC
  bool Send(const std::string& from, const std::string& to,
            const nlohmann::json& payload, const std::string& msg_type = "request");

  // Receive pending messages (max_items). Returns empty on error.
  std::vector<IpcMessage> Recv(int max_items = 20);

  // Acknowledge messages
  bool Ack(const std::vector<std::string>& msg_ids);

  // Send heartbeat
  bool Heartbeat();

  // List registered agents
  nlohmann::json ListAgents();

 private:
  IpcConfig cfg_;
  std::string service_name_;
  bool connected_ = false;

  // Execute one request (new connection per call). Returns nullopt on error.
  std::optional<nlohmann::json> Request(const nlohmann::json& req);

  // Try to re-register with daemon. Returns true on success.
  bool TryReconnect();
};
