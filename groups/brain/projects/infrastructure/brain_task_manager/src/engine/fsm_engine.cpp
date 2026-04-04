#include "brain_task_manager/engine/fsm_engine.h"

FSMEngine::FSMEngine() {
  // 完整 project_delivery 状态机
  // 对应 task_graph_schema.yaml state_mapping 和 orchestrator CLAUDE.md 阶段驱动

  // Pending: 初始态，依赖未满足
  transitions_[TaskStatus::Pending] = {
    {TaskStatus::Ready,      "ready"},    // orchestrator: 依赖全部 completed
    {TaskStatus::Cancelled,  "cancel"},
  };

  // Ready: 依赖满足，等待 orchestrator dispatch
  transitions_[TaskStatus::Ready] = {
    {TaskStatus::InProgress, "start"},    // orchestrator: worker 已派发
    {TaskStatus::Blocked,    "block"},    // 派发前发现阻塞
    {TaskStatus::Cancelled,  "cancel"},
  };

  // InProgress: worker 执行中
  transitions_[TaskStatus::InProgress] = {
    {TaskStatus::Review,     "submit"},   // worker: 实现完成，提交 review
    {TaskStatus::Blocked,    "block"},    // worker: 遇到阻塞
    {TaskStatus::Failed,     "fail"},     // worker: 不可恢复失败
    {TaskStatus::Cancelled,  "cancel"},
  };

  // Review: 等待 reviewer/qa
  transitions_[TaskStatus::Review] = {
    {TaskStatus::Verified,   "approve"},  // reviewer: review 通过
    {TaskStatus::InProgress, "reject"},   // reviewer: 不通过，打回 rework
    {TaskStatus::Blocked,    "block"},
    {TaskStatus::Cancelled,  "cancel"},
  };

  // Verified: review 通过，等待 orchestrator 最终确认
  transitions_[TaskStatus::Verified] = {
    {TaskStatus::Completed,  "done"},     // orchestrator: 验收提交
    {TaskStatus::Review,     "reopen"},   // orchestrator: 需要补充验证
  };

  // Blocked: 阻塞，等待 orchestrator 介入
  transitions_[TaskStatus::Blocked] = {
    {TaskStatus::Ready,      "unblock"},  // orchestrator: 阻塞解除，重新进入派发队列
    {TaskStatus::Cancelled,  "cancel"},
  };

  // 终态：只能归档
  transitions_[TaskStatus::Completed] = {
    {TaskStatus::Archived,   "archive"},
  };
  transitions_[TaskStatus::Failed] = {
    {TaskStatus::Archived,   "archive"},
  };
  transitions_[TaskStatus::Cancelled] = {
    {TaskStatus::Archived,   "archive"},
  };
  // Archived: terminal, no outgoing transitions
}

bool FSMEngine::CanTransition(TaskStatus from, TaskStatus to) const {
  auto it = transitions_.find(from);
  if (it == transitions_.end()) return false;
  for (auto& t : it->second) {
    if (t.to == to) return true;
  }
  return false;
}

std::string FSMEngine::TriggerName(TaskStatus from, TaskStatus to) const {
  auto it = transitions_.find(from);
  if (it == transitions_.end()) return "";
  for (auto& t : it->second) {
    if (t.to == to) return t.trigger;
  }
  return "";
}

std::vector<TaskStatus> FSMEngine::ValidTargets(TaskStatus from) const {
  std::vector<TaskStatus> result;
  auto it = transitions_.find(from);
  if (it != transitions_.end()) {
    for (auto& t : it->second) result.push_back(t.to);
  }
  return result;
}

bool FSMEngine::IsTerminal(TaskStatus s) const {
  return transitions_.find(s) == transitions_.end() || transitions_.at(s).empty();
}
