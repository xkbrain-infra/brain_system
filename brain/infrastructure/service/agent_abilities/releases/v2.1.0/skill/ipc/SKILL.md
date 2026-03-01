---
id: G-SKILL-IPC
name: ipc
description: "This skill should be used when the user asks to \"发消息给 agent\", \"通知 agent\", \"查看消息\", \"收消息\", \"找 agent\", \"通知用户\", \"发 telegram\", \"ipc send\", \"ipc recv\", or mentions inter-agent communication, IPC messaging, and user notifications."
user-invocable: true
disable-model-invocation: false
allowed-tools: mcp__brain_ipc_c__ipc_send, mcp__brain_ipc_c__ipc_recv, mcp__brain_ipc_c__ipc_search, mcp__brain_ipc_c__ipc_list_agents, mcp__brain_ipc_c__ipc_register, mcp__brain_ipc_c__conversation_create
argument-hint: "[send|recv|search|list|wait|notify] [agent_name] [message]"
---

# IPC — Agent 间通信

**工具**: `mcp-brain_ipc_c` MCP Server

## 参数解析

`/ipc $ARGUMENTS`:
- `send <agent> <message>` → `ipc_send(to=agent, message=message)`
- `recv` → `ipc_recv(wait_seconds=30)`
- `search <keyword>` → `ipc_search(query=keyword)`
- `list` → `ipc_list_agents()`（少用，优先 search）
- `wait [seconds]` → `ipc_recv(wait_seconds=N)`，默认 60s
- `notify <message>` → 通知用户（通过 telegram，见下方）
- `<agent> <message>` → 等同 `send <agent> <message>`

## 核心规则

1. **已知名字直接发送**，daemon 自动校验目标是否存在，无需手动 list
2. **不确定目标时用 `ipc_search`**，不要用 `ipc_list_agents`（返回太多）
3. **收到 [IPC] 通知**时调用 `ipc_recv`，不要后台轮询
4. **必须回复发送方**，禁止仅在控制台输出

## 发送消息

```
ipc_send(to="agent_name", message="[prefix] 内容", message_type="request")
```

- message_type: `request`（请求）、`response`（回复）、`final`（最终结果）
- priority: `critical` / `high` / `normal` / `low`

## 接收消息

```
ipc_recv(wait_seconds=30)
```

- 返回后处理消息，执行任务，再 `ipc_send` 回复结果

## 查找 Agent

```
ipc_search(query="brain-manager")   # 模糊搜索，推荐
ipc_list_agents()                    # 列出全部，仅在需要总览时用
```

## 通知用户（Telegram）

需要通知用户时，通过 IPC 发送给 `service-telegram_api`：

```
ipc_send(
  to="service-telegram_api",
  message="[NOTIFY] 通知内容",
  message_type="request",
  priority="high"
)
```

### 常见通知场景

| 场景 | 优先级 | 消息前缀 |
|------|--------|----------|
| 任务完成 | normal | `[TASK_DONE]` |
| 需要用户审批/决策 | high | `[APPROVAL_REQUEST]` |
| 构建/部署冲突 | high | `[BUILD]` |
| 严重错误/阻塞 | critical | `[ALERT]` |
| 进度报告 | low | `[PROGRESS]` |

### 通知模板

```
# 任务完成
ipc_send(to="service-telegram_api", message="[TASK_DONE] 项目 BS-023 所有任务已完成，等待验收", priority="normal")

# 需要审批
ipc_send(to="service-telegram_api", message="[APPROVAL_REQUEST] 项目 BS-024 需要 Go/No-Go 决策\n\n选项:\n1. Go — 进入开发\n2. No-Go — 回退需求阶段\n\n请回复选项编号", priority="high")

# 冲突告警
ipc_send(to="service-telegram_api", message="[BUILD] ⚠️ Merge 冲突\n域: knowledge\n冲突文件数: 3\n\n请执行: build.sh resolve knowledge", priority="high")

# 严重错误
ipc_send(to="service-telegram_api", message="[ALERT] agent-system_dev 不可恢复错误\n错误: 数据库连接失败\n已停止执行，等待人工介入", priority="critical")
```

## 回复用户

用户消息通过 frontdesk 转入。回复用户时：

```
ipc_send(to="agent-system_frontdesk", message="[REPLY] 回复内容")
```

frontdesk 会转发给 telegram_api → 用户。

## 示例

```
/ipc agent-brain-manager 请执行完整编译
/ipc send agent-system_pmo [REPORT] 任务已完成
/ipc recv
/ipc search pmo
/ipc wait 120
/ipc notify 构建完成，可以验收了
```
