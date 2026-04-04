#pragma once
#include "brain_task_manager/core/config_loader.h"
#include "brain_task_manager/core/logger.h"
#include "brain_task_manager/core/types.h"
#include "brain_task_manager/ipc/ipc_client.h"
#include "brain_task_manager/ipc/message_router.h"
#include "brain_task_manager/store/task_store.h"
#include "brain_task_manager/store/spec_store.h"
#include <atomic>
#include <string>

// EventLoop: single-threaded epoll event loop.
// Replaces Scheduler (4 poll threads) + NotifyListener (thread) + main fallback poll.
//
// epoll 监听的 fd：
//   signalfd        — SIGTERM/SIGINT → 优雅退出
//   notify socket   — brain_ipc_notify.sock 推送 → ProcessMessages()
//   timerfd x4     — heartbeat / deadline / stale-task / stale-spec
//   timerfd x1     — 按需创建的一次性重连计时器
//
// 所有事件在单线程中串行处理，无锁竞争。
class EventLoop {
public:
  EventLoop(IpcClient& ipc, MessageRouter& router,
            TaskStore& tasks, ProjectStore& specs, const Config& cfg);
  ~EventLoop();

  // 阻塞直到 SIGTERM/SIGINT 或 Stop() 被调用。
  void Run();
  void Stop();

private:
  enum FdTag : uint64_t {
    TAG_SIGNAL     = 1,
    TAG_NOTIFY     = 2,
    TAG_HEARTBEAT  = 3,
    TAG_DEADLINE   = 4,
    TAG_STALE_TASK = 5,
    TAG_STALE_SPEC = 6,
    TAG_RECONNECT  = 7,
    TAG_FALLBACK_POLL = 8,
  };

  // epoll 管理
  void EpollAdd(int fd, uint32_t events, FdTag tag);
  void EpollDel(int fd);

  // timerfd 工具
  static int  MakeTimerFd(int interval_s);        // 周期定时器
  static int  MakeOneShotTimerFd(int delay_s);    // 一次性定时器
  static void DrainTimerFd(int fd);               // 消费计数，防止 fd 持续触发

  // signalfd
  void InitSignalFd();

  // notify socket（长连接，断线自动重连）
  bool ConnectNotify();
  void DisconnectNotify();
  void OnNotifyReadable();
  void ScheduleReconnect();

  // 定时事件处理
  void OnHeartbeat();
  void OnDeadlineCheck();
  void OnStaleTaskCheck();
  void OnStaleSpecCheck();

  time_t ParseISO8601(const std::string& s) const;

  int epfd_      = -1;
  int fd_signal_ = -1;
  int fd_notify_ = -1;  // notify socket 长连接
  int fd_hb_     = -1;  // heartbeat timerfd
  int fd_dl_     = -1;  // deadline timerfd
  int fd_stask_  = -1;  // stale-task timerfd
  int fd_sspec_  = -1;  // stale-spec timerfd
  int fd_reconn_ = -1;  // 一次性重连 timerfd（按需创建）
  int fd_poll_   = -1;  // fallback poll timerfd

  std::string notify_partial_;  // notify socket 行缓冲

  IpcClient&     ipc_;
  MessageRouter& router_;
  TaskStore&     tasks_;
  ProjectStore&  specs_;
  const Config&  cfg_;

  std::atomic<bool> running_{false};
};
