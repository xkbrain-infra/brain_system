---
id: G-SKILL-FSM
name: fsm
description: "驱动项目工作流状态机推进，以及为任务创建子工作流（micro-spec）。与 task-manager 配合使用：task-manager 管理任务状态，fsm 管理工作流阶段推进逻辑。"
user-invocable: false
disable-model-invocation: false
allowed-tools: Bash
metadata:
  status: active
  source_project: /xkagent_infra/brain/base/skill/fsm
  version: "1.0.0"
---

# fsm — 工作流状态机

FSM（Finite State Machine）管理项目的**阶段推进**和**子工作流创建**。

## 与 task-manager 的分工

| 能力 | 用哪个 |
|------|--------|
| 推进项目阶段（S1→S2→...→S8） | task-manager (`project_progress`) |
| 管理任务状态（pending→in_progress→completed） | task-manager (`task_update`) |
| 检查阶段 gate 是否满足、决定是否推进 | **fsm** |
| 为一个任务创建独立的子工作流 spec | **fsm** |

## advance_state — 推进工作流阶段

在推进项目阶段前，先用 fsm 验证当前阶段的 gate 是否满足：

```python
from brain.base.skill.fsm.src.core import advance_state

result = advance_state(project_root="/xkagent_infra/groups/brain/projects/my_project")
# result.can_advance: bool
# result.failed_gates: list[str]
# result.next_state: str
```

如果 `can_advance=True`，再调用 task-manager 的 `project_progress` 实际推进。

```
fsm.advance_state → 检查 gate → 通过 → task_manager.project_progress
                                      → 不通过 → 报告 failed_gates，继续完成当前阶段
```

## create_sub_workflow — 创建子工作流

当一个任务足够复杂，需要独立的 spec 和任务图时，为它创建 micro-spec：

```python
from brain.base.skill.fsm.src.dispatcher import create_sub_workflow

create_sub_workflow(
    parent_root="/xkagent_infra/groups/brain/projects/my_project",
    task_id="BS-029-T003",
    assignee="agent-brain_dev2"
)
# 在 parent_root/sub_workflows/BS-029-T003/ 下生成独立 spec 目录
```

子工作流有自己的任务图，由 assignee agent 独立管理，完成后汇报给父工作流。

## 何时不需要 fsm

- 简单的任务状态更新 → 直接用 task-manager
- 项目阶段推进没有复杂 gate 逻辑 → 直接用 `project_progress`
- fsm 主要用于**有明确 gate 条件**的工作流（如必须有 review 通过才能进入下一阶段）
