#include "brain_task_manager/core/config_loader.h"
#include "brain_task_manager/core/logger.h"
#include "brain_task_manager/ipc/ipc_client.h"
#include "brain_task_manager/engine/fsm_engine.h"
#include "brain_task_manager/store/task_store.h"
#include "brain_task_manager/store/spec_store.h"
#include "brain_task_manager/store/project_dep_store.h"
#include "brain_task_manager/engine/dispatch_guard.h"
#include "brain_task_manager/ipc/notify_listener.h"
#include "brain_task_manager/ipc/message_router.h"
#include "brain_task_manager/engine/scheduler.h"
#include "brain_task_manager/health/health_server.h"
#include <cstdio>
#include <cstring>
#include <csignal>
#include <atomic>
#include <thread>
#include <chrono>

static std::atomic<bool> g_running{true};

static void SignalHandler(int sig) {
  (void)sig;
  g_running.store(false);
}

static void PrintUsage(const char* prog) {
  fprintf(stderr, "Usage: %s --config <path>\n", prog);
}

int main(int argc, char* argv[]) {
  // Parse args
  std::string config_path;
  for (int i = 1; i < argc; ++i) {
    if (strcmp(argv[i], "--config") == 0 && i + 1 < argc) {
      config_path = argv[++i];
    }
  }

  if (config_path.empty()) {
    PrintUsage(argv[0]);
    return 1;
  }

  // 1. Load config
  Config cfg = LoadConfig(config_path);
  SetLogLevel(cfg.log_level);

  LOG_INFO("main", LogFmt("brain_task_manager starting (service=%s)", cfg.name.c_str()));

  // Signal handlers
  signal(SIGTERM, SignalHandler);
  signal(SIGINT, SignalHandler);

  // 2. Initialize stores (load from data_dir)
  FSMEngine fsm;
  TaskStore tasks(cfg.data_dir, fsm);
  SpecStore specs(cfg.data_dir);
  ProjectDepStore deps(cfg.data_dir);
  DispatchGuard guard(cfg.data_dir);

  int task_count = tasks.Load();
  int spec_count = specs.Load();
  int dep_count  = deps.Load();
  int guard_count = guard.Load();

  LOG_INFO("main", LogFmt("stores loaded: tasks=%d specs=%d deps=%d guards=%d",
           task_count, spec_count, dep_count, guard_count));

  // 3. Connect to daemon
  IpcClient ipc(cfg.socket_path, cfg.name);
  bool connected = ipc.Connect();
  if (!connected) {
    LOG_WARN("main", "initial daemon connection failed, will retry via scheduler heartbeat");
  }

  // 4. Initialize MessageRouter
  MessageRouter router(ipc, tasks, specs, deps, guard, cfg);

  // 5. Start NotifyListener (triggers router on events)
  NotifyListener notify(cfg.notify_socket_path, cfg.name, [&]() {
    router.ProcessMessages();
  });
  notify.Start();

  // 6. Start Scheduler (heartbeat + deadline + stale scanning)
  Scheduler scheduler(ipc, tasks, specs, cfg);
  scheduler.Start();

  // 7. Start HealthServer
  HealthServer health(cfg.health_port, cfg.name, ipc, tasks, specs);
  health.Start();

  LOG_INFO("main", "all modules initialized, entering main loop");

  // 8. Main loop: fallback polling (in case notify misses events)
  while (g_running.load()) {
    router.ProcessMessages();
    for (int i = 0; i < cfg.fallback_poll_interval_s && g_running.load(); ++i) {
      std::this_thread::sleep_for(std::chrono::seconds(1));
    }
  }

  // 9. Graceful shutdown
  LOG_INFO("main", "shutting down gracefully");

  health.Stop();
  scheduler.Stop();
  notify.Stop();

  // Flush stores
  tasks.Save();
  specs.Save();
  deps.Save();
  guard.Save();

  LOG_INFO("main", "shutdown complete");
  return 0;
}
