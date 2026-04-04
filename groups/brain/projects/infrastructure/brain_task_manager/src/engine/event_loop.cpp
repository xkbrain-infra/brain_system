#include "brain_task_manager/engine/event_loop.h"
#include <sys/epoll.h>
#include <sys/timerfd.h>
#include <sys/signalfd.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <signal.h>
#include <unistd.h>
#include <cstring>
#include <ctime>

static constexpr int MAX_EVENTS = 16;

// ========== 构造 / 析构 ==========

EventLoop::EventLoop(IpcClient& ipc, MessageRouter& router,
                     TaskStore& tasks, ProjectStore& specs, const Config& cfg)
  : ipc_(ipc), router_(router), tasks_(tasks), specs_(specs), cfg_(cfg)
{
  epfd_ = epoll_create1(EPOLL_CLOEXEC);
  if (epfd_ < 0) {
    LOG_ERROR("eventloop", LogFmt("epoll_create1 failed: %s", strerror(errno)));
    return;
  }

  InitSignalFd();

  fd_hb_    = MakeTimerFd(cfg_.heartbeat_interval_s);
  fd_dl_    = MakeTimerFd(cfg_.deadline_reminder_interval_s);
  fd_stask_ = MakeTimerFd(cfg_.stale_task_interval_s);
  fd_sspec_ = MakeTimerFd(cfg_.stale_spec_interval_s);
  fd_poll_  = cfg_.fallback_poll_interval_s > 0 ? MakeTimerFd(cfg_.fallback_poll_interval_s) : -1;

  if (fd_hb_    >= 0) EpollAdd(fd_hb_,    EPOLLIN, TAG_HEARTBEAT);
  if (fd_dl_    >= 0) EpollAdd(fd_dl_,    EPOLLIN, TAG_DEADLINE);
  if (fd_stask_ >= 0) EpollAdd(fd_stask_, EPOLLIN, TAG_STALE_TASK);
  if (fd_sspec_ >= 0) EpollAdd(fd_sspec_, EPOLLIN, TAG_STALE_SPEC);
  if (fd_poll_  >= 0) EpollAdd(fd_poll_,  EPOLLIN, TAG_FALLBACK_POLL);

  if (!ConnectNotify()) ScheduleReconnect();
}

EventLoop::~EventLoop() {
  auto close_if = [](int& fd) { if (fd >= 0) { close(fd); fd = -1; } };
  close_if(fd_signal_);
  close_if(fd_notify_);
  close_if(fd_hb_);
  close_if(fd_dl_);
  close_if(fd_stask_);
  close_if(fd_sspec_);
  close_if(fd_reconn_);
  close_if(fd_poll_);
  close_if(epfd_);
}

// ========== epoll 管理 ==========

void EventLoop::EpollAdd(int fd, uint32_t events, FdTag tag) {
  struct epoll_event ev{};
  ev.events   = events;
  ev.data.u64 = static_cast<uint64_t>(tag);
  if (epoll_ctl(epfd_, EPOLL_CTL_ADD, fd, &ev) < 0)
    LOG_ERROR("eventloop", LogFmt("epoll_ctl ADD fd=%d failed: %s", fd, strerror(errno)));
}

void EventLoop::EpollDel(int fd) {
  epoll_ctl(epfd_, EPOLL_CTL_DEL, fd, nullptr);
}

// ========== timerfd 工具 ==========

int EventLoop::MakeTimerFd(int interval_s) {
  int fd = timerfd_create(CLOCK_MONOTONIC, TFD_NONBLOCK | TFD_CLOEXEC);
  if (fd < 0) {
    LOG_ERROR("eventloop", LogFmt("timerfd_create failed: %s", strerror(errno)));
    return -1;
  }
  struct itimerspec its{};
  its.it_value.tv_sec    = interval_s;
  its.it_interval.tv_sec = interval_s;
  timerfd_settime(fd, 0, &its, nullptr);
  return fd;
}

int EventLoop::MakeOneShotTimerFd(int delay_s) {
  int fd = timerfd_create(CLOCK_MONOTONIC, TFD_NONBLOCK | TFD_CLOEXEC);
  if (fd < 0) return -1;
  struct itimerspec its{};
  its.it_value.tv_sec = delay_s;
  // it_interval = 0 → 一次性触发
  timerfd_settime(fd, 0, &its, nullptr);
  return fd;
}

void EventLoop::DrainTimerFd(int fd) {
  uint64_t exp;
  // 消费超时计数，否则 EPOLLIN 持续触发
  if (read(fd, &exp, sizeof(exp)) < 0 && errno != EAGAIN) {
    // ignore
  }
}

// ========== signalfd ==========

void EventLoop::InitSignalFd() {
  sigset_t mask;
  sigemptyset(&mask);
  sigaddset(&mask, SIGTERM);
  sigaddset(&mask, SIGINT);
  // 屏蔽传统信号处理，改由 signalfd 接收
  sigprocmask(SIG_BLOCK, &mask, nullptr);

  fd_signal_ = signalfd(-1, &mask, SFD_NONBLOCK | SFD_CLOEXEC);
  if (fd_signal_ >= 0)
    EpollAdd(fd_signal_, EPOLLIN, TAG_SIGNAL);
  else
    LOG_ERROR("eventloop", LogFmt("signalfd failed: %s", strerror(errno)));
}

// ========== notify socket（长连接） ==========

bool EventLoop::ConnectNotify() {
  // AF_UNIX connect 对本地 socket 是立即完成的
  int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
  if (fd < 0) return false;

  struct sockaddr_un addr{};
  addr.sun_family = AF_UNIX;
  strncpy(addr.sun_path, cfg_.notify_socket_path.c_str(), sizeof(addr.sun_path) - 1);

  if (connect(fd, reinterpret_cast<struct sockaddr*>(&addr), sizeof(addr)) < 0) {
    LOG_WARN("eventloop", LogFmt("notify connect(%s) failed: %s",
             cfg_.notify_socket_path.c_str(), strerror(errno)));
    close(fd);
    return false;
  }

  // 订阅此 service 的消息推送
  std::string sub = "{\"action\":\"subscribe\",\"agent\":\"" + cfg_.name + "\"}\n";
  send(fd, sub.c_str(), sub.size(), MSG_NOSIGNAL);

  fd_notify_ = fd;
  // EPOLLET：边沿触发，OnNotifyReadable 需读到 EAGAIN
  EpollAdd(fd_notify_, EPOLLIN | EPOLLERR | EPOLLHUP | EPOLLET, TAG_NOTIFY);
  LOG_INFO("eventloop", "connected to notify socket");
  return true;
}

void EventLoop::DisconnectNotify() {
  if (fd_notify_ >= 0) {
    EpollDel(fd_notify_);
    close(fd_notify_);
    fd_notify_ = -1;
    notify_partial_.clear();
  }
}

void EventLoop::ScheduleReconnect() {
  if (fd_reconn_ >= 0) return;  // 已在等待中
  fd_reconn_ = MakeOneShotTimerFd(cfg_.reconnect_interval_s);
  if (fd_reconn_ >= 0) {
    EpollAdd(fd_reconn_, EPOLLIN, TAG_RECONNECT);
    LOG_INFO("eventloop", LogFmt("reconnecting to notify socket in %ds",
             cfg_.reconnect_interval_s));
  }
}

void EventLoop::OnNotifyReadable() {
  char buf[4096];
  while (true) {
    ssize_t n = recv(fd_notify_, buf, sizeof(buf) - 1, 0);
    if (n < 0) {
      if (errno == EAGAIN || errno == EWOULDBLOCK) break;  // 边沿触发，读完了
      LOG_WARN("eventloop", LogFmt("notify recv error: %s, reconnecting", strerror(errno)));
      DisconnectNotify();
      ScheduleReconnect();
      return;
    }
    if (n == 0) {
      LOG_WARN("eventloop", "notify socket closed, reconnecting");
      DisconnectNotify();
      ScheduleReconnect();
      return;
    }
    notify_partial_.append(buf, static_cast<size_t>(n));
  }

  // 按行解析（newline-delimited JSON）
  size_t pos;
  while ((pos = notify_partial_.find('\n')) != std::string::npos) {
    std::string line = notify_partial_.substr(0, pos);
    notify_partial_.erase(0, pos + 1);
    if (line.empty()) continue;

    auto j = json::parse(line, nullptr, false);
    if (j.is_discarded()) continue;

    std::string event_type = j.value("event_type", "");
    std::string target     = j.value("to", "");

    if (event_type == "ipc_message" &&
        (target == cfg_.name || target.empty())) {
      LOG_DEBUG("eventloop", "ipc_message event → ProcessMessages");
      router_.ProcessMessages();
    }
  }
}

// ========== 定时事件处理 ==========

void EventLoop::OnHeartbeat() {
  if (!ipc_.Heartbeat()) {
    LOG_WARN("eventloop", "heartbeat failed, daemon may be down");
    // heartbeat 失败说明 daemon 重启了，notify socket 也需要重连
    if (fd_notify_ < 0) ScheduleReconnect();
  }
}

void EventLoop::OnDeadlineCheck() {
  time_t now               = time(nullptr);
  time_t warning_threshold = now + cfg_.deadline_warning_hours * 3600;

  auto all_tasks = tasks_.GetAll();
  for (auto& t : all_tasks) {
    if (t.deadline.empty()) continue;
    if (t.status == TaskStatus::Completed || t.status == TaskStatus::Archived ||
        t.status == TaskStatus::Cancelled || t.status == TaskStatus::Failed) continue;

    time_t deadline = ParseISO8601(t.deadline);
    if (deadline == 0) continue;

    // 取项目 PMO（owner）
    std::string pmo;
    if (!t.project_id.empty()) {
      const SpecRecord* spec = specs_.Get(t.project_id);
      if (spec && !spec->owner.empty()) pmo = spec->owner;
    }

    if (deadline <= warning_threshold && deadline > now) {
      int hours_left = static_cast<int>((deadline - now) / 3600);
      json reminder = {
        {"event_type",      "TASK_REMINDER"},
        {"task_id",         t.task_id},
        {"title",           t.title},
        {"owner",           t.owner},
        {"deadline",        t.deadline},
        {"hours_remaining", hours_left}
      };
      if (!t.owner.empty()) {
        ipc_.Send(t.owner, reminder, "response");
        LOG_INFO("eventloop", LogFmt("deadline reminder: %s (%dh left)",
                 t.task_id.c_str(), hours_left));
      }
      if (!pmo.empty() && pmo != t.owner)
        ipc_.Send(pmo, reminder, "response");

    } else if (deadline <= now) {
      json overdue = {
        {"event_type", "TASK_OVERDUE"},
        {"task_id",    t.task_id},
        {"title",      t.title},
        {"owner",      t.owner},
        {"deadline",   t.deadline}
      };
      if (!t.owner.empty()) {
        ipc_.Send(t.owner, overdue, "response");
        LOG_WARN("eventloop", LogFmt("task overdue: %s", t.task_id.c_str()));
      }
      if (!pmo.empty() && pmo != t.owner)
        ipc_.Send(pmo, overdue, "response");
    }
  }
}

void EventLoop::OnStaleTaskCheck() {
  time_t now             = time(nullptr);
  time_t stale_threshold = now - cfg_.stale_task_hours * 3600;

  auto all_tasks = tasks_.GetAll();
  for (auto& t : all_tasks) {
    if (t.status != TaskStatus::InProgress) continue;
    if (t.updated_at.empty()) continue;

    time_t updated = ParseISO8601(t.updated_at);
    if (updated == 0 || updated >= stale_threshold) continue;

    int hours_stale = static_cast<int>((now - updated) / 3600);
    json alert = {
      {"event_type",   "TASK_STALE_ALERT"},
      {"task_id",      t.task_id},
      {"title",        t.title},
      {"owner",        t.owner},
      {"status",       TaskStatusToStr(t.status)},
      {"last_updated", t.updated_at},
      {"hours_stale",  hours_stale}
    };

    std::string pmo;
    if (!t.project_id.empty()) {
      const SpecRecord* spec = specs_.Get(t.project_id);
      if (spec && !spec->owner.empty()) pmo = spec->owner;
    }
    if (!t.owner.empty()) {
      ipc_.Send(t.owner, alert, "response");
      LOG_WARN("eventloop", LogFmt("stale task: %s (%dh inactive)",
               t.task_id.c_str(), hours_stale));
    }
    if (!pmo.empty() && pmo != t.owner)
      ipc_.Send(pmo, alert, "response");
  }
}

void EventLoop::OnStaleSpecCheck() {
  time_t now             = time(nullptr);
  time_t stale_threshold = now - cfg_.stale_spec_hours * 3600;

  SpecQueryFilter filter;
  auto all_specs = specs_.Query(filter);
  for (auto& s : all_specs) {
    if (s.stage == SpecStage::Archived || s.stage == SpecStage::S8_complete) continue;
    if (s.updated_at.empty()) continue;

    time_t updated = ParseISO8601(s.updated_at);
    if (updated == 0 || updated >= stale_threshold) continue;

    int hours_stale = static_cast<int>((now - updated) / 3600);
    json alert = {
      {"event_type",   "PROJECT_STALE_ALERT"},
      {"project_id",   s.project_id},
      {"title",        s.title},
      {"owner",        s.owner},
      {"stage",        SpecStageToStr(s.stage)},
      {"last_updated", s.updated_at},
      {"hours_stale",  hours_stale}
    };

    if (!s.owner.empty()) {
      ipc_.Send(s.owner, alert, "response");
      LOG_WARN("eventloop", LogFmt("stale project: %s (%dh inactive)",
               s.project_id.c_str(), hours_stale));
    }
  }
}

// ========== 主循环 ==========

void EventLoop::Run() {
  running_.store(true);
  LOG_INFO("eventloop", "starting epoll event loop");

  // Drain any backlog immediately after startup so the service does not depend
  // exclusively on notify delivery to begin processing requests.
  int startup_processed = router_.ProcessMessages();
  if (startup_processed > 0) {
    LOG_INFO("eventloop", LogFmt("startup fallback poll processed %d queued messages", startup_processed));
  }

  struct epoll_event events[MAX_EVENTS];
  while (running_.load()) {
    int n = epoll_wait(epfd_, events, MAX_EVENTS, -1);
    if (n < 0) {
      if (errno == EINTR) continue;
      LOG_ERROR("eventloop", LogFmt("epoll_wait failed: %s", strerror(errno)));
      break;
    }

    for (int i = 0; i < n; ++i) {
      auto     tag = static_cast<FdTag>(events[i].data.u64);
      uint32_t ev  = events[i].events;

      switch (tag) {
        case TAG_SIGNAL:
          LOG_INFO("eventloop", "received shutdown signal");
          running_.store(false);
          break;

        case TAG_NOTIFY:
          if (ev & (EPOLLERR | EPOLLHUP)) {
            LOG_WARN("eventloop", "notify socket error, reconnecting");
            DisconnectNotify();
            ScheduleReconnect();
          } else if (ev & EPOLLIN) {
            OnNotifyReadable();
          }
          break;

        case TAG_HEARTBEAT:
          DrainTimerFd(fd_hb_);
          OnHeartbeat();
          break;

        case TAG_DEADLINE:
          DrainTimerFd(fd_dl_);
          OnDeadlineCheck();
          break;

        case TAG_STALE_TASK:
          DrainTimerFd(fd_stask_);
          OnStaleTaskCheck();
          break;

        case TAG_STALE_SPEC:
          DrainTimerFd(fd_sspec_);
          OnStaleSpecCheck();
          break;

        case TAG_RECONNECT:
          DrainTimerFd(fd_reconn_);
          EpollDel(fd_reconn_);
          close(fd_reconn_);
          fd_reconn_ = -1;
          if (!ConnectNotify()) ScheduleReconnect();
          break;

        case TAG_FALLBACK_POLL: {
          DrainTimerFd(fd_poll_);
          int processed = router_.ProcessMessages();
          if (processed > 0) {
            LOG_INFO("eventloop", LogFmt("fallback poll processed %d queued messages", processed));
          }
          break;
        }
      }
    }
  }

  LOG_INFO("eventloop", "event loop stopped");
}

void EventLoop::Stop() {
  running_.store(false);
}

// ========== ISO8601 解析 ==========

time_t EventLoop::ParseISO8601(const std::string& s) const {
  if (s.empty()) return 0;
  struct tm tm_info{};
  if (strptime(s.c_str(), "%Y-%m-%dT%H:%M:%SZ", &tm_info) != nullptr)
    return timegm(&tm_info);
  if (strptime(s.c_str(), "%Y-%m-%dT%H:%M:%S", &tm_info) != nullptr)
    return timegm(&tm_info);
  return 0;
}
