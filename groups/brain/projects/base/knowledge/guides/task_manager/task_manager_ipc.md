# Task Manager IPC 使用指南

> 服务名：`service-task_manager`（常驻在线，直接 ipc_send）
> 完整 IPC 消息格式参考本文档。

---

## 消息格式总览

所有消息通过 `ipc_send(to="service-task_manager", message=json.dumps({...}))` 发送。
`event_type` 字段决定操作类型。

---

## PROJECT_CREATE — 注册项目（PMO 专属）

```json
{
  "event_type": "PROJECT_CREATE",
  "project_id": "BS-026",
  "group": "org/brain_system",
  "title": "BS-026 数据采集平台",
  "owner": "agent_brain_system_bs026_pmo"
}
```

响应：`PROJECT_CREATED`（含自动创建的 `intake_task_id`）或 `PROJECT_REJECTED`

---

## PROJECT_PROGRESS — 推进项目阶段（PMO 专属）

```json
{
  "event_type": "PROJECT_PROGRESS",
  "project_id": "BS-026",
  "target_stage": "S2_requirements"
}
```

阶段顺序（必须顺序推进）：
`S1_alignment → S2_requirements → S3_research → S4_analysis → S5_solution → S6_tasks → S7_verification → S8_complete → archived`

---

## PROJECT_QUERY — 查询项目

```json
{
  "event_type": "PROJECT_QUERY",
  "group": "org/brain_system",
  "stage": "S6_tasks"
}
```

过滤字段均可选，AND 组合。

---

## TASK_CREATE — 创建任务

```json
{
  "event_type": "TASK_CREATE",
  "task_id": "BS-026-T001",
  "project_id": "BS-026",
  "group": "org/brain_system",
  "title": "实现数据采集模块",
  "description": "详细描述",
  "owner": "agent_brain_system_bs026_dev",
  "priority": "high",
  "deadline": "2026-03-25T18:00:00Z",
  "trigger_policy": "manual",
  "participants": ["agent_brain_system_bs026_dev"],
  "review_by": "agent_brain_system_bs026_reviewer",
  "todo_list": [
    {"text": "实现核心采集逻辑", "done": false},
    {"text": "编写单元测试", "done": false}
  ],
  "depends_on": [],
  "tags": []
}
```

- `task_id`：格式建议 `{project_id}-T{序号}`，全局唯一
- `project_id`：必填，对应已注册的 project
- `priority`：`critical` / `high` / `normal` / `low`
- `deadline`：ISO 8601，如 `"2026-03-25T18:00:00Z"`，可留空
- `trigger_policy`：`manual`（默认）/ `auto` / `scheduled`

---

## TASK_UPDATE — 更新任务状态/字段

```json
{
  "event_type": "TASK_UPDATE",
  "task_id": "BS-026-T001",
  "status": "in_progress",
  "worker_id": "agent_brain_system_bs026_dev",
  "expected_version": 1
}
```

- `expected_version`：可选，用于 CAS 乐观锁防并发冲突
- 进入 `blocked` 时可附带 `blocked_reason`
- 进入 `completed`/`failed` 时可附带 `result`、`last_log_ref`、`artifact_refs`

**状态机（非终态可恢复）：**
```
pending → ready → in_progress → review → verified → completed
                    ↓                                    ↓
                  blocked ←────────────── (任意非终态) → failed / cancelled → archived
                    ↓
                  ready（unblock，retry_count 自增）
```

---

## TASK_QUERY — 查询任务

```json
{
  "event_type": "TASK_QUERY",
  "project_id": "BS-026"
}
```

或按 owner 查询：
```json
{
  "event_type": "TASK_QUERY",
  "owner": "agent_brain_system_bs026_dev"
}
```

过滤字段：`task_id`、`project_id`、`group`、`owner`、`status`，均可选，AND 组合。

---

## TASK_STATS — 获取项目任务统计

```json
{
  "event_type": "TASK_STATS",
  "project_id": "BS-026"
}
```

---

## TASK_PIPELINE_CHECK — 检查依赖 DAG

```json
{
  "event_type": "TASK_PIPELINE_CHECK",
  "project_id": "BS-026"
}
```

---

## Timer 提醒消息（service-task_manager → agent）

task_manager Scheduler 会主动发给任务 owner：

| event_type | 触发条件 | 接收方 |
|-----------|---------|--------|
| `DEADLINE_REMINDER` | 距 deadline ≤ 24h | owner + PMO |
| `OVERDUE_ALERT` | 任务已超期 | owner + PMO |
| `STALE_TASK_ALERT` | 任务 48h 无更新 | owner + PMO |

---

## 标准工作流

```
接到项目
  └─ PROJECT_CREATE（PMO）
  └─ TASK_CREATE × N（拆解任务，含 todo_list）
  └─ TASK_STATS + TASK_PIPELINE_CHECK（dispatch 前置校验）

开始每条任务
  └─ TASK_UPDATE(status=in_progress, worker_id=...)

完成每条任务
  └─ TASK_UPDATE(status=completed, result=..., artifact_refs=[...])

被阻塞
  └─ TASK_UPDATE(status=blocked, blocked_reason=...) + ipc_send 通知 PMO

Orchestrator 解除阻塞
  └─ TASK_UPDATE(status=ready)  → retry_count 自动自增，blocked_reason 自动清空
```

---

## 持久化存储结构

```
/xkagent_infra/runtime/data/brain_task_manager/
  {group}/{project_id}/
    project.json    # 项目元数据 + 当前阶段
    tasks.json      # 该项目所有任务
    events.json     # 事件历史（append-only）
  project_deps.json
  dispatch_guard.json
```

示例：group=`brain_system`，project_id=`BS-026`
→ `/xkagent_infra/runtime/data/brain_task_manager/brain_system/BS-026/tasks.json`
