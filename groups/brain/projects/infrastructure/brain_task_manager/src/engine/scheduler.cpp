#include "brain_task_manager/engine/scheduler.h"
#include <chrono>
#include <ctime>
#include <cstring>

Scheduler::Scheduler(IpcClient& ipc, TaskStore& tasks, SpecStore& specs, const Config& cfg)
  : ipc_(ipc), tasks_(tasks), specs_(specs), cfg_(cfg) {}

void Scheduler::Start() {
  if (running_.load()) return;
  running_.store(true);

  threads_.emplace_back(&Scheduler::HeartbeatLoop, this);
  threads_.emplace_back(&Scheduler::DeadlineLoop, this);
  threads_.emplace_back(&Scheduler::StaleTaskLoop, this);
  threads_.emplace_back(&Scheduler::StaleSpecLoop, this);

  LOG_INFO("scheduler", "started 4 timer threads");
}

void Scheduler::Stop() {
  running_.store(false);
  for (auto& t : threads_) {
    if (t.joinable()) t.join();
  }
  threads_.clear();
  LOG_INFO("scheduler", "all timer threads stopped");
}

void Scheduler::HeartbeatLoop() {
  while (running_.load()) {
    ipc_.Heartbeat();
    for (int i = 0; i < cfg_.heartbeat_interval_s && running_.load(); ++i) {
      std::this_thread::sleep_for(std::chrono::seconds(1));
    }
  }
}

void Scheduler::DeadlineLoop() {
  while (running_.load()) {
    // Sleep first, then scan
    for (int i = 0; i < cfg_.deadline_reminder_interval_s && running_.load(); ++i) {
      std::this_thread::sleep_for(std::chrono::seconds(1));
    }
    if (!running_.load()) break;

    time_t now = time(nullptr);
    time_t warning_threshold = now + cfg_.deadline_warning_hours * 3600;

    auto all_tasks = tasks_.GetAll();
    for (auto& t : all_tasks) {
      if (t.deadline.empty()) continue;
      if (t.status == TaskStatus::Completed || t.status == TaskStatus::Archived ||
          t.status == TaskStatus::Cancelled || t.status == TaskStatus::Failed) continue;

      time_t deadline = ParseISO8601(t.deadline);
      if (deadline == 0) continue;

      if (deadline <= warning_threshold && deadline > now) {
        int hours_left = static_cast<int>((deadline - now) / 3600);
        json reminder = {
          {"event_type", "TASK_REMINDER"},
          {"task_id", t.task_id},
          {"title", t.title},
          {"owner", t.owner},
          {"deadline", t.deadline},
          {"hours_remaining", hours_left}
        };

        // Send to task owner + spec owner (PMO)
        std::string pmo;
        if (!t.spec_id.empty()) {
          const SpecRecord* spec = specs_.Get(t.spec_id);
          if (spec && !spec->owner.empty()) pmo = spec->owner;
        }
        if (!t.owner.empty()) {
          ipc_.Send(t.owner, reminder, "response");
          LOG_INFO("scheduler", LogFmt("deadline reminder: %s (%dh left)", t.task_id.c_str(), hours_left));
        }
        if (!pmo.empty() && pmo != t.owner) {
          ipc_.Send(pmo, reminder, "response");
        }
      } else if (deadline <= now) {
        json overdue = {
          {"event_type", "TASK_OVERDUE"},
          {"task_id", t.task_id},
          {"title", t.title},
          {"owner", t.owner},
          {"deadline", t.deadline}
        };

        // Send to task owner + spec owner (PMO)
        std::string pmo;
        if (!t.spec_id.empty()) {
          const SpecRecord* spec = specs_.Get(t.spec_id);
          if (spec && !spec->owner.empty()) pmo = spec->owner;
        }
        if (!t.owner.empty()) {
          ipc_.Send(t.owner, overdue, "response");
          LOG_WARN("scheduler", LogFmt("task overdue: %s", t.task_id.c_str()));
        }
        if (!pmo.empty() && pmo != t.owner) {
          ipc_.Send(pmo, overdue, "response");
        }
      }
    }
  }
}

void Scheduler::StaleTaskLoop() {
  while (running_.load()) {
    for (int i = 0; i < cfg_.stale_task_interval_s && running_.load(); ++i) {
      std::this_thread::sleep_for(std::chrono::seconds(1));
    }
    if (!running_.load()) break;

    time_t now = time(nullptr);
    time_t stale_threshold = now - cfg_.stale_task_hours * 3600;

    auto all_tasks = tasks_.GetAll();
    for (auto& t : all_tasks) {
      if (t.status != TaskStatus::InProgress) continue;
      if (t.updated_at.empty()) continue;

      time_t updated = ParseISO8601(t.updated_at);
      if (updated == 0) continue;

      if (updated < stale_threshold) {
        int hours_stale = static_cast<int>((now - updated) / 3600);
        json alert = {
          {"event_type", "TASK_STALE_ALERT"},
          {"task_id", t.task_id},
          {"title", t.title},
          {"owner", t.owner},
          {"status", TaskStatusToStr(t.status)},
          {"last_updated", t.updated_at},
          {"hours_stale", hours_stale}
        };

        // Send to task owner + spec owner (PMO)
        std::string pmo;
        if (!t.spec_id.empty()) {
          const SpecRecord* spec = specs_.Get(t.spec_id);
          if (spec && !spec->owner.empty()) pmo = spec->owner;
        }
        if (!t.owner.empty()) {
          ipc_.Send(t.owner, alert, "response");
          LOG_WARN("scheduler", LogFmt("stale task: %s (%dh inactive)", t.task_id.c_str(), hours_stale));
        }
        if (!pmo.empty() && pmo != t.owner) {
          ipc_.Send(pmo, alert, "response");
        }
      }
    }
  }
}

void Scheduler::StaleSpecLoop() {
  while (running_.load()) {
    for (int i = 0; i < cfg_.stale_spec_interval_s && running_.load(); ++i) {
      std::this_thread::sleep_for(std::chrono::seconds(1));
    }
    if (!running_.load()) break;

    time_t now = time(nullptr);
    time_t stale_threshold = now - cfg_.stale_spec_hours * 3600;

    SpecQueryFilter filter;  // no filter = all active
    auto all_specs = specs_.Query(filter);
    for (auto& s : all_specs) {
      if (s.stage == SpecStage::Archived || s.stage == SpecStage::S8_complete) continue;
      if (s.updated_at.empty()) continue;

      time_t updated = ParseISO8601(s.updated_at);
      if (updated == 0) continue;

      if (updated < stale_threshold) {
        int hours_stale = static_cast<int>((now - updated) / 3600);
        json alert = {
          {"event_type", "SPEC_STALE_ALERT"},
          {"spec_id", s.spec_id},
          {"title", s.title},
          {"owner", s.owner},
          {"stage", SpecStageToStr(s.stage)},
          {"last_updated", s.updated_at},
          {"hours_stale", hours_stale}
        };

        if (!s.owner.empty()) {
          ipc_.Send(s.owner, alert, "response");
          LOG_WARN("scheduler", LogFmt("stale spec: %s (%dh inactive)", s.spec_id.c_str(), hours_stale));
        }
      }
    }
  }
}

time_t Scheduler::ParseISO8601(const std::string& s) const {
  if (s.empty()) return 0;
  struct tm tm_info{};
  // Parse "2026-02-23T12:34:56Z" format
  if (strptime(s.c_str(), "%Y-%m-%dT%H:%M:%SZ", &tm_info) != nullptr) {
    return timegm(&tm_info);
  }
  // Try without Z suffix
  if (strptime(s.c_str(), "%Y-%m-%dT%H:%M:%S", &tm_info) != nullptr) {
    return timegm(&tm_info);
  }
  return 0;
}
