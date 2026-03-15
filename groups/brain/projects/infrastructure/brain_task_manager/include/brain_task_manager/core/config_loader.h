#pragma once
#include "brain_task_manager/core/types.h"
#include "brain_task_manager/core/logger.h"
#include <string>
#include <fstream>

struct Config {
  // service
  std::string name              = "service-task_manager";
  std::string socket_path       = "/tmp/brain_ipc.sock";
  std::string notify_socket_path = "/tmp/brain_ipc_notify.sock";
  int         health_port       = 8091;
  std::string data_dir          = "/brain/infrastructure/service/task_manager/data/";
  LogLevel    log_level         = LogLevel::INFO;

  // scheduler
  int heartbeat_interval_s         = 60;
  int deadline_reminder_interval_s = 300;
  int stale_task_interval_s        = 3600;
  int stale_spec_interval_s        = 3600;
  int deadline_warning_hours       = 24;
  int stale_task_hours             = 48;
  int stale_spec_hours             = 72;

  // ipc
  int recv_batch_size          = 10;
  int reconnect_interval_s     = 5;
  int fallback_poll_interval_s = 5;

  // validation
  bool check_owner_online = true;
};

inline Config LoadConfig(const std::string& path) {
  Config cfg;

  std::ifstream f(path);
  if (!f.is_open()) {
    LOG_WARN("config", LogFmt("config file not found: %s, using defaults", path.c_str()));
    return cfg;
  }

  auto j = json::parse(f, nullptr, false);
  if (j.is_discarded()) {
    LOG_ERROR("config", LogFmt("failed to parse config: %s", path.c_str()));
    return cfg;
  }

  // service
  if (j.contains("service")) {
    auto& s = j["service"];
    cfg.name               = s.value("name", cfg.name);
    cfg.socket_path        = s.value("socket_path", cfg.socket_path);
    cfg.notify_socket_path = s.value("notify_socket_path", cfg.notify_socket_path);
    cfg.health_port        = s.value("health_port", cfg.health_port);
    cfg.data_dir           = s.value("data_dir", cfg.data_dir);
    std::string ll         = s.value("log_level", "INFO");
    if (ll == "DEBUG") cfg.log_level = LogLevel::DEBUG;
    else if (ll == "WARN") cfg.log_level = LogLevel::WARN;
    else if (ll == "ERROR") cfg.log_level = LogLevel::ERROR;
  }

  // scheduler
  if (j.contains("scheduler")) {
    auto& sc = j["scheduler"];
    cfg.heartbeat_interval_s         = sc.value("heartbeat_interval_s", cfg.heartbeat_interval_s);
    cfg.deadline_reminder_interval_s = sc.value("deadline_reminder_interval_s", cfg.deadline_reminder_interval_s);
    cfg.stale_task_interval_s        = sc.value("stale_task_interval_s", cfg.stale_task_interval_s);
    cfg.stale_spec_interval_s        = sc.value("stale_spec_interval_s", cfg.stale_spec_interval_s);
    cfg.deadline_warning_hours       = sc.value("deadline_warning_hours", cfg.deadline_warning_hours);
    cfg.stale_task_hours             = sc.value("stale_task_hours", cfg.stale_task_hours);
    cfg.stale_spec_hours             = sc.value("stale_spec_hours", cfg.stale_spec_hours);
  }

  // ipc
  if (j.contains("ipc")) {
    auto& ic = j["ipc"];
    cfg.recv_batch_size          = ic.value("recv_batch_size", cfg.recv_batch_size);
    cfg.reconnect_interval_s     = ic.value("reconnect_interval_s", cfg.reconnect_interval_s);
    cfg.fallback_poll_interval_s = ic.value("fallback_poll_interval_s", cfg.fallback_poll_interval_s);
  }

  // validation
  if (j.contains("validation")) {
    cfg.check_owner_online = j["validation"].value("check_owner_online", cfg.check_owner_online);
  }

  LOG_INFO("config", LogFmt("loaded config from %s", path.c_str()));
  return cfg;
}
