---
id: G-SKILL-WORKFLOW-ORCHESTRATOR
name: workflow-orchestrator
description: "当 manager、PMO、orchestrator 需要按统一编排流程执行编码任务、启动任务执行、推进阶段、落地 init 产物、或约束 pending/workspace 边界时使用。"
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Edit, Bash, Glob, Skill, mcp__mcp-brain_task_manager__project_create, mcp__mcp-brain_task_manager__project_progress, mcp__mcp-brain_task_manager__project_query, mcp__mcp-brain_task_manager__task_create, mcp__mcp-brain_task_manager__task_update, mcp__mcp-brain_task_manager__task_query, mcp__mcp-brain_ipc_c__ipc_send, mcp__mcp-brain_ipc_c__ipc_recv, mcp__mcp-brain_ipc_c__ipc_search
argument-hint: "[init|intake|research|planning|task-modeling|execution|release|audit|status] [task_or_project]"
metadata:
  status: active
  source_project: /xkagent_infra/groups/brain/projects/base
  publish_target: /xkagent_infra/brain/base/skill/workflow-orchestrator
  spec_ref: /brain/base/workflow/orchestrator_project_coding/workflow_core.yaml
---

# workflow-orchestrator

## Trigger

Use this skill when you are acting as a manager, PMO, or orchestrator for a coding task and need the workflow to be an operating constraint rather than optional reference material.

Typical triggers:
- You are about to execute or delegate a task from `runtime/tasks/*`
- You need to start a coding task and are unsure whether `init` has happened
- You need to decide whether work belongs in project workspace, pending batch, or published tree
- You are about to move from planning into implementation, dispatch, review, release, or audit

Do not use this skill for a one-off shell command with no workflow state change.

## Hard Rules

1. Start from `init` unless there is explicit evidence that `init` already completed for the current task/project.
2. Do not read or edit published `/xkagent_infra/brain/**` implementation paths as your working area.
3. If the change targets published base content, create or use a pending batch under `/xkagent_infra/runtime/update_brain/pending/<batch>/base/**` before editing.
4. Before implementation, record task/project state through `task-manager` or the task directory so the execution path is auditable.
5. Do not jump straight into source inspection or edits before deciding current phase and required artifacts.

## Entry

Choose the branch that matches the current state:

| Situation | Action |
|------|------|
| New task or unclear state | Go to [Init First](#init-first) |
| Task accepted and requirements need structuring | Go to [Intake And Planning](#intake-and-planning) |
| Tasks already modeled and workers must execute | Go to [Execution Loop](#execution-loop) |
| Code is ready for merge/release/audit | Go to [Closeout](#closeout) |

## Init First

Read these files first:
- `/brain/base/workflow/orchestrator_project_coding/workflow_core.yaml`
- `/brain/base/workflow/orchestrator_project_coding/phases/0_init.yaml`

Minimum outputs before any implementation:
- current task/project id
- chosen workspace path
- whether target is `project_root`, `pending`, or other source tree
- proof that `init` completed or an explicit `init` result you just created
- initial task state recorded via `task-manager` or task-local artifact

If the task touches published base or published brain paths:
- create/use a pending batch first
- place edits under `pending/<batch>/base/**`
- do not edit `/xkagent_infra/brain/**` directly

If `init` cannot be completed, stop and record the blocker instead of improvising execution.

## Intake And Planning

Read on demand:
- `/brain/base/workflow/orchestrator_project_coding/phases/1_intake.yaml`
- `/brain/base/workflow/orchestrator_project_coding/phases/2_research.yaml`
- `/brain/base/workflow/orchestrator_project_coding/phases/3_planning.yaml`
- `/brain/base/workflow/orchestrator_project_coding/phases/4_task_modeling.yaml`

Required behavior:
- convert the request into explicit tasks or step records
- record assumptions, blockers, and required artifacts
- decide who executes each task before implementation starts
- if execution will be delegated, make the handoff explicit and auditable

Do not treat these phase files as passive documentation. They are the decision order.

## Execution Loop

Read on demand:
- `/brain/base/workflow/orchestrator_project_coding/phases/5_execution.yaml`
- `/brain/base/workflow/orchestrator_project_coding/worker_task_protocol.yaml`

Required behavior:
- dispatch only after task state and output contract are clear
- collect results, validate, then either review, retry, or block
- keep task state transitions explicit
- when a worker or agent goes offline, move to blocker handling rather than silently continuing

If you are a manager acting directly instead of spawning a dedicated orchestrator, you still follow the same state discipline.

## Closeout

Read on demand:
- `/brain/base/workflow/orchestrator_project_coding/phases/6_release.yaml`
- `/brain/base/workflow/orchestrator_project_coding/phases/7_audit.yaml`

Before considering the task complete:
- artifacts exist at stable paths
- review/audit outcome is recorded
- publish or pending merge path is explicit
- next action is explicit: publish, restart, validate, or hand back

## Validation

The workflow is not being followed if any of these happens:
- source inspection starts before `init`
- published `/xkagent_infra/brain/**` is edited directly
- task execution begins without task/state artifact updates
- pending workflow is only entered after a gate failure
- implementation starts before phase selection is explicit

## References

| Need | Read |
|------|------|
| Core workflow contract | `/brain/base/workflow/orchestrator_project_coding/workflow_core.yaml` |
| Mandatory startup phase | `/brain/base/workflow/orchestrator_project_coding/phases/0_init.yaml` |
| Intake and requirement capture | `/brain/base/workflow/orchestrator_project_coding/phases/1_intake.yaml` |
| Research and planning | `/brain/base/workflow/orchestrator_project_coding/phases/2_research.yaml`, `/brain/base/workflow/orchestrator_project_coding/phases/3_planning.yaml` |
| Task modeling | `/brain/base/workflow/orchestrator_project_coding/phases/4_task_modeling.yaml` |
| Execution and dispatch loop | `/brain/base/workflow/orchestrator_project_coding/phases/5_execution.yaml` |
| Release and audit | `/brain/base/workflow/orchestrator_project_coding/phases/6_release.yaml`, `/brain/base/workflow/orchestrator_project_coding/phases/7_audit.yaml` |
| Worker handoff contract | `/brain/base/workflow/orchestrator_project_coding/worker_task_protocol.yaml` |
