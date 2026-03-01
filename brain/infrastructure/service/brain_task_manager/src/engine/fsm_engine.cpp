#include "brain_task_manager/engine/fsm_engine.h"

FSMEngine::FSMEngine() {
  // 11 transitions matching S4 analysis state_model_decision
  transitions_[TaskStatus::Pending] = {
    {TaskStatus::InProgress, "start"},
    {TaskStatus::Cancelled,  "cancel"},
  };
  transitions_[TaskStatus::InProgress] = {
    {TaskStatus::Blocked,    "block"},
    {TaskStatus::Completed,  "complete"},
    {TaskStatus::Failed,     "fail"},
    {TaskStatus::Cancelled,  "cancel"},
  };
  transitions_[TaskStatus::Blocked] = {
    {TaskStatus::InProgress, "unblock"},
    {TaskStatus::Cancelled,  "cancel"},
  };
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
