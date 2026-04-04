#include "brain_task_manager/core/config_loader.h"
#include "brain_task_manager/core/logger.h"
#include "brain_task_manager/ipc/ipc_client.h"
#include "brain_task_manager/engine/fsm_engine.h"
#include "brain_task_manager/store/task_store.h"
#include "brain_task_manager/store/spec_store.h"
#include "brain_task_manager/store/event_store.h"
#include "brain_task_manager/store/project_dep_store.h"
#include "brain_task_manager/engine/dispatch_guard.h"
#include "brain_task_manager/ipc/message_router.h"
#include "brain_task_manager/engine/event_loop.h"
#include "brain_task_manager/health/health_server.h"
#include <cstdio>
#include <cstring>

static void PrintUsage(const char* prog) {
  fprintf(stderr, "Usage: %s --config <path>\n", prog);
}

int main(int argc, char* argv[]) {
  std::string config_path;
  for (int i = 1; i < argc; ++i) {
    if (strcmp(argv[i], "--config") == 0 && i + 1 < argc) {
      config_path = argv[++i];
    }
  }
  if (config_path.empty()) { PrintUsage(argv[0]); return 1; }

  // 1. 配置
  Config cfg = LoadConfig(config_path);
  SetLogLevel(cfg.log_level);
  LOG_INFO("main", LogFmt("brain_task_manager starting (service=%s)", cfg.name.c_str()));

  // 2. 初始化 stores
  FSMEngine       fsm;
  ProjectStore    projects(cfg.data_dir);
  TaskStore       tasks(cfg.data_dir, fsm);
  EventStore      events(cfg.data_dir);
  ProjectDepStore deps(cfg.data_dir);
  DispatchGuard   guard(cfg.data_dir);

  int proj_count  = projects.Load();
  int task_count  = tasks.Load();
  int dep_count   = deps.Load();
  int guard_count = guard.Load();

  LOG_INFO("main", LogFmt("stores loaded: projects=%d tasks=%d deps=%d guards=%d",
           proj_count, task_count, dep_count, guard_count));

  // 3. 连接 daemon（失败时 event loop 的 heartbeat 会自动重试）
  IpcClient ipc(cfg.socket_path, cfg.name);
  if (!ipc.Connect())
    LOG_WARN("main", "initial daemon connection failed, will retry via heartbeat");

  // 4. 消息路由
  MessageRouter router(ipc, tasks, projects, events, deps, guard, cfg);

  // 5. 健康检查 HTTP（独立线程）
  HealthServer health(cfg.health_port, cfg.name, ipc, tasks, projects);
  health.Start();

  LOG_INFO("main", "all modules initialized, entering event loop");

  // 6. epoll 事件循环（阻塞直到 SIGTERM/SIGINT）
  //    - notify socket：消息推送 → ProcessMessages()
  //    - timerfd x4  ：heartbeat / deadline / stale-task / stale-spec
  //    - signalfd    ：优雅退出
  EventLoop loop(ipc, router, tasks, projects, cfg);
  loop.Run();

  // 7. 优雅关闭，刷盘
  LOG_INFO("main", "shutting down gracefully");
  health.Stop();

  tasks.Save();
  projects.Save();
  deps.Save();
  guard.Save();

  LOG_INFO("main", "shutdown complete");
  return 0;
}
