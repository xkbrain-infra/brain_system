#pragma once
#include "brain_task_manager/core/types.h"
#include <string>
#include <map>
#include <utility>
#include <vector>

// FSM Engine: validates task status transitions
// 7 states, 11 transitions (backward compatible with task_manager C)
class FSMEngine {
public:
  FSMEngine();

  // Validate if transition from current to target status is allowed.
  // Returns true if valid, false otherwise.
  bool CanTransition(TaskStatus from, TaskStatus to) const;

  // Get the trigger name for a transition (for logging).
  std::string TriggerName(TaskStatus from, TaskStatus to) const;

  // Get all valid target states from a given state.
  std::vector<TaskStatus> ValidTargets(TaskStatus from) const;

  // Check if a state is terminal (no outgoing transitions).
  bool IsTerminal(TaskStatus s) const;

private:
  struct Transition {
    TaskStatus to;
    std::string trigger;
  };

  // from_state -> list of valid transitions
  std::map<TaskStatus, std::vector<Transition>> transitions_;
};
