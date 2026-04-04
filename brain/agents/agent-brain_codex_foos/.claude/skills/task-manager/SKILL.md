---
id: G-SKILL-TASK-MANAGER
name: task-manager
description: "当需要创建项目、创建任务、更新任务状态、查询任务列表、推进项目阶段、或进行任何与 brain_task_manager 服务交互的操作时使用。"
user-invocable: true
disable-model-invocation: false
allowed-tools: mcp__mcp-brain_task_manager__project_create, mcp__mcp-brain_task_manager__project_progress, mcp__mcp-brain_task_manager__project_query, mcp__mcp-brain_task_manager__project_dependency_set, mcp__mcp-brain_task_manager__project_dependency_query, mcp__mcp-brain_task_manager__task_create, mcp__mcp-brain_task_manager__task_update, mcp__mcp-brain_task_manager__task_query, mcp__mcp-brain_task_manager__task_delete, mcp__mcp-brain_task_manager__task_stats, mcp__mcp-brain_task_manager__task_pipeline_check
argument-hint: "[project-create|project-progress|project-query|task-create|task-update|task-query|task-stats|pipeline-check] [args...]"
metadata:
  status: active
  source_project: /xkagent_infra/groups/brain/projects/infrastructure/brain_task_manager
  publish_target: /xkagent_infra/brain/base/skill/task-manager
  version: "1.0.0"
  mcp_server: mcp-brain_task_manager
---

# /task-manager — 任务与项目管理

**工具**: `mcp-brain_task_manager` MCP Server（IPC → `service-brain_task_manager`）

---

## 触发场景

| 情境 | 操作 |
|------|------|
| 创建新项目 | → [project_create](#project_create) |
| 推进项目到下一阶段 | → [project_progress](#project_progress) |
| 查看项目列表或详情 | → [project_query](#project_query) |
| 创建新任务 | → [task_create](#task_create) |
| 更新任务状态/字段 | → [task_update](#task_update) |
| 查询任务列表 | → [task_query](#task_query) |
| 查看项目任务统计 | → [task_stats](#task_stats) |
| 检查依赖图是否合法 | → [task_pipeline_check](#task_pipeline_check) |
| 设置/查询项目间依赖 | → [project_dependency_set / query](#项目依赖) |

---

## 任务状态机

```
Pending → Ready → InProgress → Review → Verified → Completed
                      ↕
                   Blocked（可恢复）

任意非终态 → Failed / Cancelled / Archived（终态，不可逆）
```

**状态转换规则**：
- `pending → ready`：依赖满足后，orchestrator 手动或自动触发
- `ready → in_progress`：orchestrator 派发，同时填 `worker_id`
- `in_progress → blocked`：执行遇阻，填 `blocked_reason`
- `blocked → ready`：unblock，`retry_count` 自动+1
- `in_progress → review`：worker 完成，提交 review
- `review → in_progress`：reject/rework，`retry_count` 自动+1
- `review → verified`：reviewer 通过
- `verified → completed`：orchestrator 确认，填 `result`

---

## project_create

创建项目。自动生成 `{project_id}-intake` kickoff 任务。

```python
project_create(
    project_id="BS-028",
    group="brain_system",
    title="新功能开发",
    owner="agent-brain_pmo"
)
# → {"status": "ok", "project_id": "BS-028", "intake_task_id": "BS-028-intake"}
```

## project_progress

推进项目阶段（必须顺序推进）：
`S1_alignment → S2_requirements → S3_research → S4_analysis → S5_solution → S6_tasks → S7_verification → S8_complete`

```python
project_progress(project_id="BS-028", target_stage="S2_requirements")
# → {"status": "ok", "to_stage": "S2_requirements"}
```

## project_query

查询项目，所有字段可选：

```python
project_query(group="brain_system", stage="S6_tasks")
# → {"status": "ok", "projects": [...], "count": N}
```

---

## task_create

```python
task_create(
    task_id="BS-028-T001",
    project_id="BS-028",
    group="brain_system",
    title="实现数据采集模块",
    owner="agent-brain_pmo",
    priority="high",              # critical|high|normal|low
    description="详细说明...",
    deadline="2026-04-15T00:00:00Z",
    trigger_policy="manual",      # manual|auto|scheduled
    review_by="agent-brain_reviewer",
    depends_on=["BS-028-T000"],
    todo_list=[{"text": "子任务1"}, {"text": "子任务2"}],
    tags=["backend", "data"],
)
# → {"status": "ok", "task_id": "BS-028-T001"}
```

## task_update

更新任务，所有字段可选（task_id 必填）：

```python
# 派发任务（pending/ready → in_progress）
task_update(
    task_id="BS-028-T001",
    status="in_progress",
    worker_id="agent-brain_dev1",
    expected_version=1,           # 可选，CAS 乐观锁
)

# 报告阻塞
task_update(task_id="BS-028-T001", status="blocked", blocked_reason="等待外部 API 接入")

# 提交 review
task_update(task_id="BS-028-T001", status="review")

# 完成任务
task_update(
    task_id="BS-028-T001",
    status="completed",
    result="模块已实现，通过所有测试",
    artifact_refs=["/xkagent_infra/groups/brain/.../src/collector.py"],
)

# 更新 todo_list
task_update(
    task_id="BS-028-T001",
    todo_list=[{"text": "子任务1", "done": True}, {"text": "子任务2", "done": False}],
    note="完成了子任务1",  # 写入 events.yaml
)
```

## task_query

```python
# 查询项目内所有 in_progress 任务
task_query(project_id="BS-028", status="in_progress")

# 查询某个 agent 负责的所有任务
task_query(owner="agent-brain_dev1")

# 精确查某个任务
task_query(task_id="BS-028-T001")

# → {"status": "ok", "tasks": [...], "count": N}
```

## task_stats

```python
task_stats(project_id="BS-028")
# → {
#     "status": "ok",
#     "total": 12,
#     "by_status": {"pending": 3, "in_progress": 4, "review": 2, "completed": 3},
#     "by_priority": {"high": 6, "normal": 6}
#   }
```

## task_pipeline_check

检查任务依赖图的合法性（环检测 + 缺失依赖）：

```python
task_pipeline_check(project_id="BS-028")
# → {
#     "valid": true,
#     "total_tasks": 12,
#     "ready_tasks": 3,
#     "blocked_tasks": 1,
#     "cycle_detected": false,
#     "missing_dependencies": []
#   }
```

---

## 项目依赖

```python
# 设置项目间依赖（BS-028 依赖 BS-026 完成后才能开始）
project_dependency_set(project_id="BS-028", depends_on=["BS-026"])

# 查询依赖关系
project_dependency_query(project_id="BS-028")
# → {"depends_on": ["BS-026"], "downstream": ["BS-029"]}
```

---

## 常见错误

| 错误 | 原因 | 处理 |
|------|------|------|
| `version conflict` | CAS 版本不匹配，任务被他人修改 | 先 `task_query` 取最新 version，再重试 |
| `illegal status transition` | 状态机不允许该跳转 | 按状态机路径逐步推进 |
| `owner agent not online` | owner agent 未注册到 IPC daemon | 确认 agent 在线，或临时关闭 `check_owner_online` |
| `task_id already exists` | task_id 重复 | 换一个唯一 ID |
| `timeout after 15s` | service-brain_task_manager 未运行 | 检查服务状态 |
