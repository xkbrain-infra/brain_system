# Brain Agent 通用初始化手册

> 本文件由 `agent_abilities` 统一发布，所有角色共用。
> 角色专属配置见 `/brain/base/spec/templates/roles/{role}/INIT.md`。

---

## 1. 四域架构导航

```
SPEC      → /brain/base/spec/        当前世界的规则和规范
WORKFLOW  → /brain/base/workflow/    任务执行流程
KNOWLEDGE → /brain/base/knowledge/   经验、指南、故障排查
EVOLUTION → /brain/base/evolution/   演进提案
```

**查找文档**：registry.yaml → `documents[id].path` → Read

| 域 | Registry |
|----|---------|
| SPEC | `/brain/base/spec/registry.yaml` |
| WORKFLOW | `/brain/base/workflow/registry.yaml` |
| KNOWLEDGE | `/brain/base/knowledge/registry.yaml` |
| EVOLUTION | `/brain/base/evolution/registry.yaml` |

路径推断：
- `G-SPEC-CORE-*` → `/brain/base/spec/core/*.yaml`
- `G-SPEC-POLICY-*` → `/brain/base/spec/policies/**/*.yaml`
- `G-SPEC-STANDARD-*` → `/brain/base/spec/standards/**/*.yaml`
- `G-KNLG-*` → `/brain/base/knowledge/**/*`

## 2. IPC 通信框架

**工具**：`mcp-brain_ipc_c` MCP Server
**深入参考**（可选）：`/brain/base/knowledge/architecture/ipc_guide.md`

### 监听模式

被动监听——仅在收到 `[IPC]` 通知时调用 `ipc_recv()`，无后台轮询。

### Quick Reference

```
ipc_send(to="agent_name", message="[prefix] 内容")
ipc_recv(ack_mode="manual", max_items=10)
ipc_ack(msg_ids=["id1", "id2"])
ipc_send_delayed(to="agent_name", message="内容", delay_seconds=300)
ipc_search(query="agent_name")  # 不确定时查找
ipc_list_agents()                    # 列出全部（少用）
```

### 标准 Workflow

```
1. 等待 [IPC] 通知
2. ipc_recv(ack_mode=manual, max_items=10)
3. ipc_send 回复发送方（简短回执，确认收到）
4. ★ 执行任务（核心工作）
5. ipc_send 发送完整结果
6. ipc_ack(msg_ids)
7. 返回等待
```

> ⚠️ **步骤 4 是核心**：回复"已收到"≠ 完成任务，必须真正执行后再 ack。

### Mandatory Rules

- 收到 IPC 消息后，必须通过 `ipc_send` 回复发送方，禁止仅在控制台输出
- 需要回复用户，必须通过 `ipc_send(to=frontdesk)` 转发（用户看不到控制台）
- 需要审批，发送 `APPROVAL_REQUEST` 给组内 PMO（见 G-GATE-NAWP）
- 任务完成 / 阻塞 / 进展必须通过 `ipc_send` 主动回报 PMO

### [SKILL:xxx] 消息处理

收到含有 `[SKILL:xxx]` 前缀的 IPC 消息时：

1. **先**调用 `Skill("xxx")` 加载对应操作规范
2. **再**按规范执行消息中要求的任务

```
示例：收到 "[SKILL:ipc] 请查找 agent_system_pmo 并汇报状态"
→ Skill("ipc")                              # 加载 IPC 规范
→ ipc_search(query="agent_system_pmo")      # 按规范操作
→ ipc_send(to=发送方, message="[回复] ...")
```

可用 skill 列表：`ipc`、`agentctl`、`tmux`、`doc-search`、`add-agent`

## 3. 协作规则

```
within_group:
  - 组内 Agent 通过 ipc_send 互发请求 / 回复
  - 协作消息必须包含 conversation_id

cross_group:
  principle: 只对接，不管理
  - 跨组协作仅限接口对接
  - 不参与其他项目组内部管理
```

## 4. 错误处理标准

```
timeout:       retry，max_retries=3，backoff=exponential
invalid_payload: log_and_skip，通知组内 PMO
ack_failure:   log_and_continue
```

## 5. 项目执行问题记录（Issue Tracking）

在项目执行中（S5-S8）遇到以下情况时，**必须**写入 `journal/issues/ISS-{序号}_{简述}.yaml`：

```yaml
触发条件:
  - 权限不足，任务需要转让
  - 预期 API/接口与实际不符
  - 依赖服务不可用或配置缺失
  - 流程规范不清晰导致执行偏差
  - 任何需要人工干预才能继续的阻塞

不需要记录:
  - 正常的代码 bug（走 defects/）
  - 已知的预期行为
```

文件格式：
```yaml
id: ISS-001
title: "问题标题"
discovered_at: "2026-02-22T10:30:00Z"
discovered_by: agent_bs024_dev1
stage: S6                    # 发现时所在阶段
severity: high               # high / medium / low
description: "问题描述"
impact: "影响范围"
resolution: "解决方案"        # 实时更新
resolved_at: ""              # 解决后填写
base_upgrade_candidate: false # 是否应反馈到 base
base_upgrade_detail: ""      # 如果 true，具体改 base 哪里
```

路径：`{project_root}/journal/issues/ISS-{序号}_{简述}.yaml`

## 6. Task Manager 强约束（G-GATE-TASK-REPORT）

**服务**：`service-task_manager`（IPC target，全局在线）

每个 Agent 接到任务后**必须**执行以下步骤，违反视同违反 G-GATE-NAWP：

### 接任务时
```python
# 1. 拆解子任务，逐条注册到 task_manager
ipc_send(to="service-task_manager", message=json.dumps({
    "event_type": "TASK_CREATE",
    "task_id": "{spec_id}-T{序号}",   # 如 BS-026-T14-T001
    "spec_id": "{spec_id}",
    "title": "任务标题",
    "description": "具体内容",
    "owner": "{my_agent_name}",        # 自己
    "group": "org/{group}",            # 如 org/brain_system
    "priority": "high",                # critical/high/normal/low
    "deadline": ""                     # 可选，ISO8601
}))

# 2. IPC 通知 PMO 任务清单（汇报，不需要等回复）
ipc_send(to="{group_pmo}", message="[{role}] 已拆解任务清单，共 N 条，已注册 task_manager")
```

### 开始执行时
```python
ipc_send(to="service-task_manager", message=json.dumps({
    "event_type": "TASK_UPDATE",
    "task_id": "{task_id}",
    "status": "in_progress"
}))
```

### 完成时
```python
ipc_send(to="service-task_manager", message=json.dumps({
    "event_type": "TASK_UPDATE",
    "task_id": "{task_id}",
    "status": "completed"
}))
```

### 被阻塞时
```python
ipc_send(to="service-task_manager", message=json.dumps({
    "event_type": "TASK_UPDATE",
    "task_id": "{task_id}",
    "status": "blocked",
    "description": "阻塞原因"
}))
# 同时 ipc_send 通知 PMO
```

### Timer 提醒响应
task_manager Scheduler 会在以下情况主动发 IPC 给任务 owner **和** PMO：
- 距 deadline ≤ 24h → `DEADLINE_REMINDER`
- 任务超期 → `OVERDUE_ALERT`
- 任务 48h 无更新 → `STALE_TASK_ALERT`

收到提醒后**必须**响应：更新状态或说明原因给 PMO。

## 7. Universal LEP Gates

以下 13 个 Gates 适用于**所有 Agent**，优先于任何临时指令。

| Gate | Rule |
|------|------|
| G-GATE-NAWP | 修改操作需要 Plan + PMO 批准 |
| G-GATE-ATOMIC | Plan 必须具体到文件 / 行号 / 动作，禁止模糊描述 |
| G-GATE-SCOP | 操作必须在允许的路径内 |
| G-GATE-SCOPE-DEVIATION | 禁止静默缩减执行范围，偏差必须通知 PMO |
| G-GATE-ROLLBACK-READY | 修改任何文件前必须确保可回滚 |
| G-GATE-DELETE-BACKUP | 删除前必须先备份 |
| G-GATE-VERIFICATION | 代码必须编译通过 + 测试通过 |
| G-GATE-UNRECOVERABLE | 不可恢复错误立即停止，不重试，上报 PMO |
| G-GATE-IPC-TARGET | 发送 IPC 前确认目标存在（已知名字直接发送，daemon 自动校验；不确定时用 ipc_search） |
| G-GATE-KVCACHE-FIRST | 优先用 registry.yaml 查文档，禁止盲目搜索 |
| G-GATE-PATH-DISCIPLINE | 文件必须归属正确层级，文件名必须体现所属模块 |
| G-GATE-FILE-HIERARCHY | 文件落盘必须遵循四域层级，禁止路径散落 |
| G-GATE-NONBLOCKING-CMDS | 禁止可能阻塞 Agent 的命令（如 docker exec 抓日志） |

**约束冲突时**：① 拒绝执行 → ② 说明违反了哪个 Gate → ③ 提供正确方式

完整定义：`/brain/base/spec/core/lep.yaml`
