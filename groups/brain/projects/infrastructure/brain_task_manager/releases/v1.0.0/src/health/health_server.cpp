#include "brain_task_manager/health/health_server.h"

// Disable OpenSSL support - we only need plain HTTP for health checks
#ifdef CPPHTTPLIB_OPENSSL_SUPPORT
#undef CPPHTTPLIB_OPENSSL_SUPPORT
#endif
#include <httplib.h>

HealthServer::HealthServer(int port, const std::string& service_name,
                           IpcClient& ipc, TaskStore& tasks, SpecStore& specs)
  : port_(port), service_name_(service_name),
    ipc_(ipc), tasks_(tasks), specs_(specs), start_time_(time(nullptr)) {}

void HealthServer::Start() {
  if (running_.load()) return;
  running_.store(true);
  thread_ = std::thread(&HealthServer::ServerLoop, this);
}

void HealthServer::Stop() {
  running_.store(false);
  if (thread_.joinable()) thread_.join();
}

void HealthServer::ServerLoop() {
  httplib::Server svr;

  svr.Get("/health", [this](const httplib::Request& /*req*/, httplib::Response& res) {
    bool connected = ipc_.IsConnected();
    time_t now = time(nullptr);
    int uptime = static_cast<int>(now - start_time_);

    json body = {
      {"status", connected ? "ok" : "degraded"},
      {"service", service_name_},
      {"uptime_s", uptime},
      {"tasks_count", tasks_.Count()},
      {"specs_count", specs_.Count()},
      {"ipc_connected", connected},
      {"last_heartbeat", NowUTC()}
    };

    if (connected) {
      res.status = 200;
    } else {
      res.status = 503;
    }

    res.set_content(body.dump(), "application/json");
  });

  LOG_INFO("health", LogFmt("starting health server on port %d", port_));

  // Listen with a 1-second timeout check so we can stop
  svr.set_keep_alive_timeout(1);

  // Run in a way that can be stopped
  std::thread listener([&svr, this]() {
    svr.listen("0.0.0.0", port_);
  });

  // Wait until stop is requested
  while (running_.load()) {
    std::this_thread::sleep_for(std::chrono::seconds(1));
  }

  svr.stop();
  if (listener.joinable()) listener.join();

  LOG_INFO("health", "health server stopped");
}
