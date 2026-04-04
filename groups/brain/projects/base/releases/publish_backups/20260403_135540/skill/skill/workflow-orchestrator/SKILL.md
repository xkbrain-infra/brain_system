---
id: G-SKILL-WORKFLOW-ORCHESTRATOR
name: workflow-orchestrator
description: "当 manager、PMO、orchestrator 需要严格按 orchestrator workflow 推进任务时使用。"
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Skill, mcp__mcp-brain_task_manager__project_query, mcp__mcp-brain_task_manager__task_query, mcp__mcp-brain_ipc_c__ipc_send, mcp__mcp-brain_ipc_c__ipc_recv, mcp__mcp-brain_ipc_c__ipc_search
argument-hint: "[init|intake|research|planning|task-modeling|execution|release|audit|status] [task_or_project]"
metadata:
  status: active
  source_project: /xkagent_infra/groups/brain/projects/base
  publish_target: /xkagent_infra/brain/base/skill/workflow-orchestrator
  spec_ref: /brain/base/workflow/orchestrator_project_coding/workflow_core.yaml
---

# workflow-orchestrator

## 用途

当 workflow 不是“参考资料”，而是“必须执行的顺序约束”时，使用本 skill。

适用角色：
- manager
- pmo
- orchestrator

## Core 骨架

这个 workflow 的 phase/step 顺序是固定的，不能自己发明新流程。

- 8 个 phase：
  - init
  - intake
  - research
  - planning
  - task_modeling
  - execution
  - release
  - audit

- 15 个 step：
  - `MWF-OPC:0_1:environment_init`
  - `MWF-OPC:1_1:capture_requirement`
  - `MWF-OPC:1_2:classify_unknowns`
  - `MWF-OPC:2_1:research_if_needed`
  - `MWF-OPC:3_1:define_plan`
  - `MWF-OPC:3_2:create_spec_checklist`
  - `MWF-OPC:4_1:model_tasks`
  - `MWF-OPC:5_1:dispatch_ready_tasks`
  - `MWF-OPC:5_2:collect_results`
  - `MWF-OPC:5_2b:dispatch_review`
  - `MWF-OPC:5_3:resolve_blocker`
  - `MWF-OPC:5_4:evaluate_release_readiness`
  - `MWF-OPC:6_1:drive_release`
  - `MWF-OPC:7_1:run_audit`
  - `MWF-OPC:7_2:workflow_complete`

硬规则：
- 第一检查点永远是 `MWF-OPC:0_1:environment_init`
- 没有明确 init 完成证据，不允许进入 intake/planning/execution
- 系统级需求也不能跳过 init

## 第一动作

第一步永远不是 Explore，不是看实现，不是看历史文档。

第一步只做两件事：
1. 读 `/brain/base/workflow/orchestrator_project_coding/workflow_core.yaml`
2. 读 `/brain/base/workflow/orchestrator_project_coding/phases/0_init.yaml`

在这两步之前，禁止：
- Explore
- 批量 Read / Glob / Grep
- 读取 `.previous/docs/**`
- 读取 `/xkagent_infra/brain/infrastructure/service/**/current/**`
- 读取 `groups/**` 实现源码
- 使用 Bash 做目录探索或架构排查

## 核心规则

1. workflow 的第一阶段永远是 `init`。
2. 没有明确 `init` 完成证据前，不允许进入 `intake/planning`。
3. 没有明确 `init` 完成证据前，不允许读代码，不允许改代码，不允许创建 pending。
4. 命中 `G-GATE-SVC-ENCAP` 说明 lane 走错了，必须立刻回到 workflow，不要继续试读实现。
5. 本 skill 故意不提供 `Glob/Grep/Bash/Edit`；manager 在这个阶段只允许读 workflow、写 `runtime/tasks/<task>/` 下的 planning 文档、调用 query-only task_manager 和 IPC。
6. manager 只允许 `project_query/task_query`；`project_create/task_create/task_update/project_progress` 由 PMO 负责。

## Init 只检查什么

只检查下面这些证据是否存在：
- 当前 task / project 身份
- `execution_environment` 是否为 `sandbox`
- sandbox/container 是否存在且 `healthy`
- runtime mount / IPC / agentctl / task_manager 是否 reachable
- `MWF-OPC:0_1:environment_init` 是否 completed

如果任一项缺失：
- 输出 blocker
- 停在 `init`
- 不进入下一阶段

## Manager 边界

manager 在 workflow 中只做：
- 判定 phase
- 做 init gate 判断
- 写 intake / contract
- 拆 task / dispatch
- 做 review / acceptance

manager 不做：
- 不直接读 dashboard / sandbox_service / task_manager 实现
- 不直接接实现任务
- 不因执行角色不在线就把实现任务改挂自己
- 不直接执行 `sandboxctl create|start|stop|destroy|exec`
- 不直接创建或推进 task_manager 项目/任务

## 进入 Intake 的前提

只有在 `init` 明确完成后，才允许进入 intake / planning。

进入后只做：
- 定义 contract / data model
- 定义 acceptance criteria
- 拆 task / owner
- 在 `/xkagent_infra/runtime/tasks/<task_id>/` 下写 `INTAKE.md`、`contract.yaml`、`task_split.yaml`
- 通过 IPC / PMO 请求 task_manager 变更，不直接自己写入 task_manager

做完后，manager 必须停下，等待执行角色。

## 系统级需求的处理方式

像下面这类需求：
- dashboard 展示
- sandbox / project 绑定
- 跨 service 数据联动

也必须按同样顺序：
1. 先做 `init`
2. 再写 contract
3. 再拆任务
4. 再派发给 dev / devops

不要用“先理解架构”为理由去读 published service 实现。
不要把 planning 文档写到 `groups/**/pending/**`。
真正待发布的改动批次由执行角色在 `/xkagent_infra/runtime/update_brain/pending/<batch>/` 下创建。

## 最短执行顺序

对 manager 来说，正确顺序只有这条：

1. 读 `workflow_core.yaml`
2. 读 `phases/0_init.yaml`
3. 做 `init` 判定
4. `init` 未完成：报 blocker 并停止
5. `init` 已完成：在 `runtime/tasks/<task>/` 下写 intake / contract / task split
6. 派发给执行角色
7. manager 停止，不进入实现
