#include "brain_task_manager/ipc/ipc_client.h"
#include <cstring>

std::optional<json> IpcClient::DoRequest(const json& req) {
  int fd = socket(AF_UNIX, SOCK_STREAM, 0);
  if (fd < 0) {
    LOG_ERROR("ipc", LogFmt("socket() failed: %s", strerror(errno)));
    return std::nullopt;
  }

  struct sockaddr_un addr{};
  addr.sun_family = AF_UNIX;
  strncpy(addr.sun_path, socket_path_.c_str(), sizeof(addr.sun_path) - 1);

  if (connect(fd, reinterpret_cast<struct sockaddr*>(&addr), sizeof(addr)) < 0) {
    LOG_ERROR("ipc", LogFmt("connect(%s) failed: %s", socket_path_.c_str(), strerror(errno)));
    close(fd);
    connected_.store(false);
    return std::nullopt;
  }

  // Send request (JSON + newline)
  std::string payload = req.dump() + "\n";
  ssize_t sent = send(fd, payload.c_str(), payload.size(), MSG_NOSIGNAL);
  if (sent < 0 || static_cast<size_t>(sent) != payload.size()) {
    LOG_ERROR("ipc", LogFmt("send() failed: %s", strerror(errno)));
    close(fd);
    return std::nullopt;
  }

  // Receive response (read until newline)
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
    LOG_ERROR("ipc", "empty response from daemon");
    return std::nullopt;
  }

  auto resp = json::parse(buf, nullptr, false);
  if (resp.is_discarded()) {
    LOG_ERROR("ipc", LogFmt("failed to parse response: %.200s", buf.c_str()));
    return std::nullopt;
  }

  return resp;
}

std::optional<json> IpcClient::Request(const json& req) {
  std::lock_guard<std::mutex> lock(mu_);
  return DoRequest(req);
}

bool IpcClient::Connect() {
  json req = {{"action", "service_register"}, {"data", {
    {"service_name", service_name_},
    {"metadata", {{"type", "brain_task_manager"}, {"version", "0.1.0"}}}
  }}};

  auto resp = Request(req);
  if (!resp || resp->value("status", "") != "ok") {
    LOG_ERROR("ipc", "service_register failed");
    connected_.store(false);
    return false;
  }

  connected_.store(true);
  LOG_INFO("ipc", LogFmt("registered as %s", service_name_.c_str()));
  return true;
}

bool IpcClient::Heartbeat() {
  json req = {{"action", "service_heartbeat"}, {"data", {
    {"service_name", service_name_}
  }}};

  auto resp = Request(req);
  if (!resp || resp->value("status", "") != "ok") {
    connected_.store(false);
    return false;
  }
  connected_.store(true);
  return true;
}

std::optional<std::string> IpcClient::Send(const std::string& to, const json& payload,
                                            const std::string& message_type,
                                            const std::string& conversation_id) {
  json data = {
    {"from", service_name_},
    {"to", to},
    {"payload", payload},
    {"message_type", message_type}
  };
  if (!conversation_id.empty()) {
    data["conversation_id"] = conversation_id;
  }

  json req = {{"action", "ipc_send"}, {"data", data}};
  auto resp = Request(req);
  if (!resp || resp->value("status", "") != "ok") {
    LOG_WARN("ipc", LogFmt("ipc_send to %s failed", to.c_str()));
    return std::nullopt;
  }

  return resp->value("msg_id", "");
}

std::vector<json> IpcClient::Recv(int max_items) {
  json req = {{"action", "ipc_recv"}, {"data", {
    {"agent", service_name_},
    {"ack_mode", "manual"},
    {"max_items", max_items}
  }}};

  auto resp = Request(req);
  if (!resp || resp->value("status", "") != "ok") {
    return {};
  }

  std::vector<json> msgs;
  if (resp->contains("messages") && (*resp)["messages"].is_array()) {
    for (auto& m : (*resp)["messages"]) {
      msgs.push_back(m);
    }
  }
  return msgs;
}

int IpcClient::Ack(const std::vector<std::string>& msg_ids) {
  if (msg_ids.empty()) return 0;

  json req = {{"action", "ipc_ack"}, {"data", {
    {"agent", service_name_},
    {"msg_ids", msg_ids}
  }}};

  auto resp = Request(req);
  if (!resp) return 0;
  return resp->value("acked", 0);
}

json IpcClient::ListAgents(bool include_offline) {
  json req = {{"action", "agent_list"}, {"data", {
    {"include_offline", include_offline}
  }}};

  auto resp = Request(req);
  if (!resp || resp->value("status", "") != "ok") return json::array();

  if (resp->contains("agents")) return (*resp)["agents"];
  return json::array();
}
