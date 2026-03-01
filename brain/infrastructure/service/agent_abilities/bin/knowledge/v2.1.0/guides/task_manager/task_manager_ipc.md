# Task Manager IPC 使用指南

> 服务名：`service-task_manager`（常驻在线，直接 ipc_send）
> 完整 IPC 消息格式参考本文档。

---

## 消息格式总览

所有消息通过 `ipc_send(to="service-task_manager", message=json.dumps({...}))` 发送。
`event_type` 字段决定操作类型。

---

## TASK_CREATE — 创建任务

```json
{
  "event_type": "TASK_CREATE",
  "task_id": "BS-026-T14-T001",
  "spec_id": "BS-026-T14",
  "title": "实现数据采集模块",
  "description": "详细描述",
  "owner": "agent-brain_system_bs026_dev",
  "group": "org/brain_system",
  "priority": "high",
  "deadline": "",
  "depends_on": [],
  "tags": []
}
```

- `task_id`：格式 `{spec_id}-T{序号}`，全局唯一
- `priority`：`critical` / `high` / `normal` / `low`
- `deadline`：ISO8601，如 `"2026-02-25T18:00:00Z"`，可留空

---

## TASK_UPDATE — 更新任务状态

```json
{
  "event_type": "TASK_UPDATE",
  "task_id": "BS-026-T14-T001",
  "status": "in_progress",
  "description": "可选：补充说明"
}
```

- `status`：`pending` / `in_progress` / `completed` / `blocked`

---

## TASK_QUERY — 查询任务

```json
{
  "event_type": "TASK_QUERY",
  "spec_id": "BS-026-T14"
}
```

或按 owner 查询：

```json
{
  "event_type": "TASK_QUERY",
  "owner": "agent-brain_system_bs026_dev"
}
```

---

## SPEC_CREATE — 注册 Spec（PMO 专属）

```json
{
  "event_type": "SPEC_CREATE",
  "spec_id": "BS-026-T14",
  "title": "BS-026 T14 实现任务",
  "owner": "agent-brain_system_bs026_pmo",
  "group": "org/brain_system"
}
```

---

## SPEC_PROGRESS — 更新 Spec 进度（PMO 专属）

```json
{
  "event_type": "SPEC_PROGRESS",
  "spec_id": "BS-026-T14",
  "stage": "S6",
  "note": "任务分发完成"
}
```

---

## Timer 提醒消息（service-task_manager → agent）

task_manager Scheduler 会主动发给任务 owner **和** spec owner（PMO）：

| event_type | 触发条件 | 接收方 |
|-----------|---------|--------|
| `DEADLINE_REMINDER` | 距 deadline ≤ 24h | owner + PMO |
| `OVERDUE_ALERT` | 任务已超期 | owner + PMO |
| `STALE_TASK_ALERT` | 任务 48h 无更新 | owner + PMO |

收到提醒后**必须**：
1. 更新任务状态（`TASK_UPDATE`）
2. 或向 PMO 说明原因

---

## 标准工作流（每个 role 执行）

```
接到任务
  └─ SPEC_CREATE（PMO）
  └─ TASK_CREATE × N（自己拆解）
  └─ ipc_send 通知 PMO 任务清单

开始每条任务
  └─ TASK_UPDATE(in_progress)

完成每条任务
  └─ TASK_UPDATE(completed)

被阻塞
  └─ TASK_UPDATE(blocked) + ipc_send 通知 PMO

收到 timer 提醒
  └─ 响应更新状态或说明原因给 PMO
```
