#pragma once
#include "config.h"
#include "hot_reload.h"
#include "http_server.h"
#include "ipc_bridge.h"
#include "permission.h"
#include "rate_limiter.h"
#include "router.h"
#include "traffic_stats.h"

#include <atomic>
#include <memory>
#include <thread>

class Gateway {
 public:
  explicit Gateway(AppConfig cfg);
  ~Gateway();

  // Start all threads and HTTP server. Blocks until shutdown.
  // Returns false if startup fails (e.g. IPC daemon unreachable).
  bool Run();

  // Signal shutdown (called from signal handler)
  void Shutdown();

 private:
  void IpcPollerLoop();
  void HeartbeatLoop();
  void StatsFlushLoop();
  void ProcessMessage(const IpcMessage& msg);

  AppConfig cfg_;

  IpcBridge ipc_;
  Router router_;
  TrafficStats stats_;
  Permission perm_;
  RateLimiter rate_limiter_;

  std::atomic<bool> running_{false};
  std::atomic<bool> ipc_connected_{false};
  std::atomic<uint64_t> uptime_s_{0};

  std::unique_ptr<HttpServer> http_;
  std::unique_ptr<HotReloadManager> hot_reload_;
  std::thread ipc_poller_thread_;
  std::thread heartbeat_thread_;
  std::thread stats_flush_thread_;
  std::thread uptime_thread_;

  void ReloadConfig();
};
