#include "ipc_bridge.h"
#include "logger.h"

#include <cerrno>
#include <cstring>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

IpcBridge::IpcBridge(const IpcConfig& cfg, std::string service_name)
    : cfg_(cfg), service_name_(std::move(service_name)) {}

IpcBridge::~IpcBridge() {}

// brain_ipc is a one-request-per-connection protocol (like HTTP/1.0).
// Each Request() opens a fresh socket, sends one JSON action, reads one
// JSON response, then closes the socket.  This matches daemon_client.py.
static std::optional<nlohmann::json> DoRequest(const std::string& socket_path,
                                                const nlohmann::json& req) {
  int fd = socket(AF_UNIX, SOCK_STREAM, 0);
  if (fd < 0) {
    LOG_ERROR("ipc_bridge", LogFmt("socket() failed: %s", strerror(errno)));
    return std::nullopt;
  }

  struct sockaddr_un addr{};
  addr.sun_family = AF_UNIX;
  strncpy(addr.sun_path, socket_path.c_str(), sizeof(addr.sun_path) - 1);

  if (connect(fd, reinterpret_cast<struct sockaddr*>(&addr), sizeof(addr)) < 0) {
    LOG_ERROR("ipc_bridge", LogFmt("connect(%s) failed: %s",
                                    socket_path.c_str(), strerror(errno)));
    close(fd);
    return std::nullopt;
  }

  std::string payload = req.dump() + "\n";
  ssize_t sent = send(fd, payload.c_str(), payload.size(), MSG_NOSIGNAL);
  if (sent < 0) {
    LOG_ERROR("ipc_bridge", LogFmt("send() failed: %s", strerror(errno)));
    close(fd);
    return std::nullopt;
  }

  // Read until newline
  std::string buf;
  buf.reserve(4096);
  char tmp[4096];
  while (true) {
    ssize_t n = recv(fd, tmp, sizeof(tmp) - 1, 0);
    if (n <= 0) break;
    buf.append(tmp, static_cast<size_t>(n));
    if (buf.find('\n') != std::string::npos) break;
  }
  close(fd);

  if (buf.empty()) {
    LOG_ERROR("ipc_bridge", "empty response from daemon");
    return std::nullopt;
  }

  auto parsed = nlohmann::json::parse(buf, nullptr, /*allow_exceptions=*/false);
  if (parsed.is_discarded()) {
    LOG_ERROR("ipc_bridge", "response parse error: invalid JSON");
    return std::nullopt;
  }
  return parsed;
}

bool IpcBridge::Connect() {
  // Verify daemon is reachable by sending a ping-style register
  nlohmann::json reg_req = {
      {"action", "service_register"},
      {"data", {
          {"service_name", service_name_},
          {"metadata", {{"type", "gateway"}}}
      }}
  };
  auto resp = DoRequest(cfg_.socket_path, reg_req);
  if (!resp || (*resp).value("status", "") != "ok") {
    LOG_ERROR("ipc_bridge", LogFmt("service_register failed for %s", service_name_.c_str()));
    connected_ = false;
    return false;
  }
  connected_ = true;
  LOG_INFO("ipc_bridge", LogFmt("connected and registered as %s", service_name_.c_str()));
  return true;
}

void IpcBridge::Disconnect() {
  connected_ = false;
}

bool IpcBridge::TryReconnect() {
  LOG_INFO("ipc_bridge", "attempting reconnect...");
  return Connect();
}

std::optional<nlohmann::json> IpcBridge::Request(const nlohmann::json& req) {
  auto resp = DoRequest(cfg_.socket_path, req);
  if (!resp) {
    connected_ = false;
  }
  return resp;
}

bool IpcBridge::Send(const std::string& from, const std::string& to,
                     const nlohmann::json& payload, const std::string& msg_type) {
  nlohmann::json req = {
      {"action", "ipc_send"},
      {"data", {
          {"from", from},
          {"to",   to},
          {"payload", payload},
          {"message_type", msg_type}
      }}
  };
  auto resp = Request(req);
  if (!resp) {
    TryReconnect();
    resp = Request(req);
  }
  return resp && (*resp).value("status", "") == "ok";
}

std::vector<IpcMessage> IpcBridge::Recv(int max_items) {
  nlohmann::json req = {
      {"action", "ipc_recv"},
      {"data", {
          {"agent",     service_name_},
          {"ack_mode",  "manual"},
          {"max_items", max_items}
      }}
  };
  auto resp = Request(req);
  if (!resp) {
    TryReconnect();
    return {};
  }

  std::vector<IpcMessage> msgs;
  if (!resp->contains("messages") || !(*resp)["messages"].is_array()) return msgs;

  for (auto& m : (*resp)["messages"]) {
    IpcMessage msg;
    msg.msg_id       = m.value("msg_id", "");
    msg.from         = m.value("from", "");
    msg.to           = m.value("to", "");
    msg.message_type = m.value("message_type", "");
    if (m.contains("payload")) msg.payload = m["payload"];
    msgs.push_back(std::move(msg));
  }
  return msgs;
}

bool IpcBridge::Ack(const std::vector<std::string>& msg_ids) {
  if (msg_ids.empty()) return true;
  nlohmann::json req = {
      {"action", "ipc_ack"},
      {"data", {
          {"agent",   service_name_},
          {"msg_ids", msg_ids}
      }}
  };
  auto resp = Request(req);
  return resp && (*resp).value("status", "") == "ok";
}

bool IpcBridge::Heartbeat() {
  nlohmann::json req = {
      {"action", "service_heartbeat"},
      {"data", {{"service_name", service_name_}}}
  };
  auto resp = Request(req);
  if (!resp) {
    TryReconnect();
    return false;
  }
  return (*resp).value("status", "") == "ok";
}

nlohmann::json IpcBridge::ListAgents() {
  nlohmann::json req = {
      {"action", "agent_list"},
      {"data", {{"include_offline", false}}}
  };
  auto resp = Request(req);
  if (!resp) {
    TryReconnect();
    return nlohmann::json::object();
  }
  return *resp;
}
