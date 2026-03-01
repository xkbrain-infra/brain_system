#include "brain_task_manager/ipc/notify_listener.h"
#include <cstring>
#include <chrono>

NotifyListener::NotifyListener(const std::string& socket_path,
                               const std::string& service_name,
                               EventCallback on_event)
  : socket_path_(socket_path), service_name_(service_name), on_event_(on_event) {}

void NotifyListener::Start() {
  if (running_.load()) return;
  running_.store(true);
  thread_ = std::thread(&NotifyListener::ListenLoop, this);
}

void NotifyListener::Stop() {
  running_.store(false);
  if (thread_.joinable()) thread_.join();
}

void NotifyListener::ListenLoop() {
  LOG_INFO("notify", LogFmt("starting notify listener on %s", socket_path_.c_str()));

  while (running_.load()) {
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) {
      LOG_ERROR("notify", LogFmt("socket() failed: %s", strerror(errno)));
      std::this_thread::sleep_for(std::chrono::seconds(2));
      continue;
    }

    struct sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, socket_path_.c_str(), sizeof(addr.sun_path) - 1);

    if (connect(fd, reinterpret_cast<struct sockaddr*>(&addr), sizeof(addr)) < 0) {
      LOG_WARN("notify", LogFmt("connect(%s) failed: %s, retrying in 2s",
               socket_path_.c_str(), strerror(errno)));
      close(fd);
      std::this_thread::sleep_for(std::chrono::seconds(2));
      continue;
    }

    // Send subscribe request
    std::string subscribe_msg = "{\"action\":\"subscribe\",\"agent\":\"" + service_name_ + "\"}\n";
    send(fd, subscribe_msg.c_str(), subscribe_msg.size(), MSG_NOSIGNAL);

    LOG_INFO("notify", "connected to notify socket, listening for events");

    // Read events in a loop
    char buf[4096];
    std::string partial;

    while (running_.load()) {
      // Set read timeout so we can check running_ periodically
      struct timeval tv;
      tv.tv_sec = 2;
      tv.tv_usec = 0;
      setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

      ssize_t n = recv(fd, buf, sizeof(buf) - 1, 0);
      if (n < 0) {
        if (errno == EAGAIN || errno == EWOULDBLOCK) continue;  // timeout, check running_
        LOG_WARN("notify", LogFmt("recv error: %s, reconnecting", strerror(errno)));
        break;
      }
      if (n == 0) {
        LOG_WARN("notify", "notify socket closed, reconnecting");
        break;
      }

      partial.append(buf, static_cast<size_t>(n));

      // Process complete lines (newline-delimited JSON)
      size_t pos;
      while ((pos = partial.find('\n')) != std::string::npos) {
        std::string line = partial.substr(0, pos);
        partial.erase(0, pos + 1);

        if (line.empty()) continue;

        auto j = json::parse(line, nullptr, false);
        if (j.is_discarded()) continue;

        // Check if this event is for us
        std::string event_type = j.value("event_type", "");
        std::string target = j.value("to", "");

        if (event_type == "ipc_message" &&
            (target == service_name_ || target.empty())) {
          LOG_DEBUG("notify", "received ipc_message event, triggering handler");
          if (on_event_) on_event_();
        }
      }
    }

    close(fd);

    if (running_.load()) {
      LOG_INFO("notify", "reconnecting to notify socket in 2s");
      std::this_thread::sleep_for(std::chrono::seconds(2));
    }
  }

  LOG_INFO("notify", "notify listener stopped");
}
