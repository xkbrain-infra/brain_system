---
id: G-SKILL-WORKFLOW-ORCHESTRATOR
name: workflow-orchestrator
description: "当 manager、PMO、orchestrator 需要按统一编排流程执行编码任务、启动任务执行、推进阶段、落地 init 产物、或约束 pending/sandbox 边界时使用。"
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
6. `init` is not complete just because local `state/*.yaml` files exist. `init` completes only when the sandbox and external validation evidence exist.
7. No code reading or code editing is allowed before the `init` gate is passed.
8. If the `init` gate is closed, stop at blocker reporting. Do not create pending batches, do not inspect source under `groups/**`, and do not implement a “可先做一部分” fallback.

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

If the task touches published base or published brain paths:
- create/use a pending batch first
- place edits under `pending/<batch>/base/**`
- do not edit `/xkagent_infra/brain/**` directly

Use this order. Do not skip forward:

1. Identify scope.
   Required outputs:
   - current task or project id
   - target path class: `project_root`, `pending`, or other source tree
   - why this task belongs there

   Guardrail:
   - a published implementation path such as `/xkagent_infra/brain/infrastructure/service/**` is never a valid `project_root`
   - if the task targets published implementation, create or resolve a delivery workspace under `group_root/projects/{project_id}` and carry the implementation path only as a target/artifact reference

2. Confirm the execution environment.
   Required evidence:
   - workflow says `execution_environment: sandbox`
   - chosen sandbox id
   - proof that sandbox bootstrap is expected for this run

3. Check bootstrap prerequisites from Phase 0.
   Required evidence:
   - task_manager/spec record exists when the workflow requires it
   - pending batch or project_root exists
   - orchestrator runtime target is known

4. Verify sandbox readiness.
   Required evidence:
   - sandbox/container exists
   - container health is `healthy`
   - project mount exists and is writable where expected
   - brain mount exists and remains read-only
   - git branch is correct
   - IPC, agentctl, and task_manager reachability checks pass

5. Verify orchestration handshakes.
   Required evidence:
   - `ORCHESTRATOR_READY` sent
   - `PROCEED_CONFIRMED` received
   - `SANDBOX_VERIFY_REQUEST` sent
   - `SANDBOX_VERIFY_RESULT` received and passed

6. Verify persistent init artifacts.
   Required evidence:
   - `state/global_config.yaml`
   - `state/project_snapshot.yaml`
   - `state/step_results/.../completion_check.yaml`
   - task_manager step status shows `MWF-OPC:0_1:environment_init = completed`

Only after all six checks pass may you read implementation code or start edits.

These do not count as init completion:
- creating `state/` directories alone
- writing `global_config.yaml` or `project_snapshot.yaml` without sandbox proof
- seeing an existing pending batch but no sandbox/validation evidence
- assuming init passed because files were staged earlier

If any required evidence is missing:
- stay in `init`
- record the exact blocker
- request the missing bootstrap or verification step
- send a blocker report back to the requester / PMO
- return immediately after the blocker report
- do not enter execution or code modification
- do not create pending batches
- do not read `groups/**` or service implementation source

### Manager Bootstrap Dispatch

If you are acting as `manager`, the workflow requires `execution_environment=sandbox`, and bootstrap has not been actively dispatched yet, you must do this before any other action:

1. Emit an explicit bootstrap handoff to `agent-brain_devops`.
   Required payload:
   - `message_type: BOOTSTRAP_DISPATCH`
   - `project_id`
   - `project_root`
   - `sandbox_strategy`
   - `runtime_root=/xkagent_infra/runtime/sandbox/{sandbox_id}`
   - `forbidden_fallback=host_project_agent_creation`
2. Notify PMO / requester that the task is now in `init/bootstrap`.
3. Stop and wait for `BOOTSTRAP_COMPLETE`, `BOOTSTRAP_FAILED`, or an explicit blocker.

Manager boundary:
- do not run `sandboxctl create|start|stop|destroy|exec` yourself
- do not “help devops a little bit” by creating the sandbox first
- you may inspect status after dispatch, but the executor stays `agent-brain_devops`

Do not replace this handoff with:
- reading implementation source
- creating a pending batch
- creating a host-level orchestrator
- probing a host `agent-brain_orch`
- pointing `project_root` at the implementation source tree itself
- running `sandboxctl create --with-agent orchestrator` from the manager session

### Init Gate

Before moving to execution, explicitly answer all of these with concrete evidence:

- Is there a sandbox id?
- Is the container healthy?
- Is the workspace mounted correctly?
- Is the branch correct?
- Are IPC, agentctl, and task_manager reachable?
- Has external verification passed?
- Is `MWF-OPC:0_1:environment_init` completed in task/state records?

If any answer is `no` or `unknown`, the gate is closed.

### Forbidden Shortcuts

These are workflow violations:
- creating local init files and then immediately editing code
- treating pending staging as equivalent to sandbox bootstrap
- creating a pending batch after init-gate failure and then using it to justify source inspection
- reading service implementation before the init gate passes
- reading `groups/**` source because artifacts listed target files or because the role thinks it has standing authorization
- entering `execution` because a batch already exists
- inventing init success without external validation artifacts

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
- implementation starts before sandbox-ready evidence exists
- local yaml files are treated as a substitute for container health or external verification

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
