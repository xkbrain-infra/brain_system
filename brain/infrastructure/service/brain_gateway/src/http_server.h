#pragma once
#include "config.h"
#include "ipc_bridge.h"
#include "permission.h"
#include "rate_limiter.h"
#include "router.h"
#include "traffic_stats.h"

#define CPPHTTPLIB_NO_EXCEPTIONS
#include <httplib.h>
#include <memory>
#include <string>

class HttpServer {
 public:
  HttpServer(const AppConfig& cfg,
             IpcBridge& ipc,
             Router& router,
             TrafficStats& stats,
             Permission& perm,
             RateLimiter& rate_limiter,
             std::atomic<uint64_t>& uptime_s,
             std::atomic<bool>& ipc_connected);

  // Start listening (blocks until stop() is called)
  bool Listen();

  // Stop the HTTP server
  void Stop();

 private:
  void RegisterRoutes();

  const AppConfig& cfg_;
  IpcBridge& ipc_;
  Router& router_;
  TrafficStats& stats_;
  Permission& perm_;
  RateLimiter& rate_limiter_;
  std::atomic<uint64_t>& uptime_s_;
  std::atomic<bool>& ipc_connected_;
  httplib::Server svr_;
};
