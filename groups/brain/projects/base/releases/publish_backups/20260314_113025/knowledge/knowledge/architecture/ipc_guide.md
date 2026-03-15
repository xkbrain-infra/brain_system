# IPC 通信系统使用指南

> Brain 系统 Agent 间消息通信的完整使用手册。所有 Agent 通过 IPC 发送和接收消息，实现协作、审批、状态回报等功能。

## 概述

IPC (Inter-Process Communication) 是 Brain 系统的消息总线，由两部分组成：

| 组件 | 实现 | 职责 |
|------|------|------|
| brain_ipc | C 程序，常驻后台 | 消息路由、队列管理、ACK/重试、延迟投递、定时调度、Agent 注册 |
| brain-ipc-c | MCP Server，随 Agent 启动 | 将 daemon 能力封装为 MCP 工具，供 Agent 直接调用 |

### 架构图

```
┌───────────────────────────────────────────────────────────────────┐
│  Agent A (tmux session)       Agent B (非 tmux, 直接 CLI)        │
│  ┌─────────────┐              ┌─────────────┐                    │
│  │ Claude/Codex │             │ Claude CLI   │                    │
│  │  调用 MCP 工具│             │  调用 MCP 工具│                    │
│  └──────┬──────┘              └──────┬──────┘                    │
│         │                           │                            │
│  ┌──────▼──────┐              ┌──────▼──────┐                    │
│  │ brain-ipc-c │              │ brain-ipc-c │                    │
│  │ MCP Server  │              │ MCP Server  │                    │
│  │ agent_register             │ service_register                 │
│  │ (tmux_pane)  │             │ (pty_path)   │                   │
│  └──────┬──────┘              └──────┬──────┘                    │
│         │ Unix Socket                │                           │
│         └───────────┐   ┌────────────┘                           │
│                     ▼   ▼                                        │
│              ┌──────────────┐                                    │
│              │ brain_ipc │                                    │
│              │  消息路由     │    通知方式:                        │
│              │  队列管理     │    tmux agent → tmux send-keys     │
│              │  ACK/重试     │    非 tmux   → pty write           │
│              │  延迟投递     │    MCP 长轮询 → notify socket       │
│              │  定时调度     │                                    │
│              └──────────────┘                                    │
│              /tmp/brain_ipc.sock                               │
└───────────────────────────────────────────────────────────────────┘
```

### 注册与通知机制

Agent 有两种注册身份，MCP Server 启动时自动选择：

| 环境 | 注册方式 | 推送通知方式 | 原理 |
|------|---------|-------------|------|
| tmux 会话内 | `agent_register` (带 tmux_pane) | `tmux send-keys` | 模拟用户输入，文本进入 LLM context |
| 非 tmux (直接 CLI) | `service_register` (带 pty_path) | `write()` 到 pty 设备 | 写入终端 stdin，文本进入 LLM context |
| MCP 长轮询 | `ipc_recv(wait_seconds=N)` | notify socket 唤醒 | MCP Server 内部机制，不占 LLM token |

**关键**：无论哪种方式，通知文本格式统一为：
```
[IPC] New message from <sender> (msg_id=<id>). Run: ipc_recv(ack_mode=manual) then ipc_ack
```

---

## 快速开始

**你不需要做任何初始化操作**。MCP Server 启动时会自动完成 Agent 注册和心跳维护。

你只需要关注标准工作流：

```
1. 等待 [IPC] 通知消息出现
2. 调用 ipc_recv(ack_mode="manual", max_items=10) 拉取消息
3. 阅读并处理消息内容
4. 调用 ipc_send(to=发送方, message="回复内容") 回复发送方 ← 必须！
5. 调用 ipc_ack(msg_ids=[...]) 确认已处理的消息
6. 回到步骤 1 等待下一条
```

**关键规则**：收到 IPC 消息后，**必须**通过 `ipc_send` 回复发送方。禁止仅在控制台输出结果。

---

## MCP 工具参考（Agent 可用的 7 个工具）

### 1. ipc_send — 发送消息

向其他 Agent 发送一条消息。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `to` | string | 是 | 目标 Agent 名称，如 `"agent_system_devops"` |
| `message` | string | 是 | 消息内容文本 |
| `conversation_id` | string | 否 | 会话 ID（多轮对话时使用） |
| `message_type` | string | 否 | `"request"` / `"response"` / `"final"` |
| `priority` | string | 否 | `"critical"` / `"high"` / `"normal"` / `"low"` |
| `priority_reason` | string | 否 | 优先级说明（当 priority 为 critical/high 时建议填写） |

**示例**：

```
ipc_send(
  to="agent_system_devops",
  message="[architect] 请检查 Redis 集群状态，确认所有节点健康",
  priority="high",
  priority_reason="用户反馈延迟异常"
)
```

**返回值**：
```json
{
  "status": "ok",
  "msg_id": "a1b2c3d4",
  "to": "agent_system_devops@agent_system_devops:%89"
}
```

---

### 2. ipc_recv — 接收消息

拉取发给自己的待处理消息。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `conversation_id` | string | 否 | 只拉取指定会话的消息 |
| `ack_mode` | string | 否 | `"auto"` (默认，收即确认) 或 `"manual"` (需手动 ack) |
| `max_items` | number | 否 | 最多拉取条数，默认 100 |
| `wait_seconds` | number | 否 | 长轮询等待秒数 (0=立即返回, 最大 120)。内部使用 notify socket 唤醒，不浪费 token |

**推荐用法**：始终使用 `ack_mode="manual"`，处理完再手动 ack。

```
ipc_recv(ack_mode="manual", max_items=10)
```

**返回值**：
```json
{
  "status": "ok",
  "count": 2,
  "messages": [
    {
      "msg_id": "uuid-1",
      "from": "agent_system_pmo@agent_system_pmo:%87",
      "to": "agent_system_devops@agent_system_devops:%89",
      "payload": {
        "content": "[pmo] 请部署 cxx_service v3.1 到 staging 环境",
        "priority": "high"
      },
      "message_type": "request",
      "conversation_id": "conv-123",
      "ts": 1738234567
    }
  ],
  "ack_required": true
}
```

**消息字段说明**：

| 字段 | 说明 |
|------|------|
| `msg_id` | 消息唯一 ID，ack 时需要 |
| `from` | 发送方的实例 ID |
| `payload.content` | 消息正文 |
| `payload.priority` | 优先级 |
| `message_type` | request=请求, response=回复, final=最终回复 |
| `conversation_id` | 会话 ID（如有） |
| `ts` | 发送时间戳（Unix） |

---

### 3. ipc_ack — 确认消息

确认已处理的消息（仅 `ack_mode="manual"` 时需要）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `msg_ids` | string[] | 是 | 要确认的消息 ID 数组 |

```
ipc_ack(msg_ids=["uuid-1", "uuid-2"])
```

**注意**：未 ack 的消息在超时后会被重新投递（最多重试 5 次）。处理完消息后务必 ack。

---

### 4. ipc_send_delayed — 延迟发送

在指定秒数后投递消息。主要用于 PMO 自提醒和超时检查。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `to` | string | 是 | 目标 Agent 名称 |
| `message` | string | 是 | 消息内容 |
| `delay_seconds` | number | 是 | 延迟秒数（1 ~ 86400，即 1 秒 ~ 24 小时） |
| `conversation_id` | string | 否 | 会话 ID |
| `message_type` | string | 否 | 消息类型 |

**示例 — PMO 自提醒**：
```
ipc_send_delayed(
  to="agent_system_pmo",
  message="CHECK task-001 of agent_system_architect",
  delay_seconds=1800
)
```

**返回值**：
```json
{
  "status": "scheduled",
  "msg_id": "uuid",
  "send_at": 1738236367
}
```

---

### 5. ipc_list_agents — 查询在线 Agent

列出所有已注册的 Agent 及其状态。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `include_offline` | boolean | 否 | 是否包含离线 Agent，默认 false |

**返回值**（instances 数组中每个实例的字段）：

| 字段 | 说明 |
|------|------|
| `agent_name` | 逻辑名称 |
| `instance_id` | 完整实例 ID |
| `tmux_session` | tmux 会话名（tmux agent 有值） |
| `tmux_pane` | tmux pane ID（tmux agent 有值） |
| `pty_path` | PTY 设备路径（非 tmux agent 有值，如 `/dev/pts/3`） |
| `source` | 注册来源: `register` / `tmux_discovery` / `service` / `heartbeat` |
| `online` | 是否在线 |

**用途**：派任务前确认目标 Agent 在线；调试消息投递问题。

---

### 6. ipc_register — 注册 Agent

将自己注册到 daemon 的 Agent 注册表中。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `agent_name` | string | 否 | Agent 名称（默认取环境变量 BRAIN_AGENT_NAME） |
| `metadata` | string | 否 | JSON 格式的元数据 |

**行为**：
- **有 tmux pane**：走 `agent_register`，附带 tmux_pane 和 tmux_session
- **无 tmux（直接 CLI）**：走 `service_register`，附带当前进程的 pty 设备路径（从 `/proc/self/fd/0` 读取）

**通常不需要手动调用**。MCP Server 启动时会自动注册。

---

### 7. conversation_create — 创建多方会话

创建一个有多个参与者的会话，用于多 Agent 协作讨论。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `participants` | string | 是 | 逗号分隔的参与者列表 |
| `metadata` | string | 否 | JSON 格式的会话元数据 |

```
conversation_create(
  participants="agent_system_pmo,agent_system_architect,agent_system_devops",
  metadata='{"topic":"cxx_service v3.1 部署评审"}'
)
```

---

## Daemon 完整 API 参考

以下是 brain_ipc 支持的所有 action（通过 Unix Socket JSON 协议调用）。Agent 通常不直接调用这些 API，而是通过 MCP 工具间接使用。

### 核心消息 API

| Action | 说明 | 对应 MCP 工具 |
|--------|------|--------------|
| `ipc_send` | 发送消息到目标 Agent 队列 | `ipc_send` |
| `ipc_recv` | 从自己的队列拉取消息 | `ipc_recv` |
| `ipc_ack` | 确认消息已处理 | `ipc_ack` |
| `ipc_send_delayed` | 延迟投递消息 | `ipc_send_delayed` |
| `ipc_status` | 获取 daemon 内部状态统计 | - |

### Agent 注册 API

| Action | 说明 | 对应 MCP 工具 |
|--------|------|--------------|
| `agent_register` | tmux Agent 注册（需 tmux_session + tmux_pane） | `ipc_register` (tmux 环境) |
| `agent_heartbeat` | tmux Agent 心跳 | 自动 |
| `agent_list` | 列出所有注册的 Agent | `ipc_list_agents` |
| `agent_unregister` | 注销 Agent | - |
| `service_register` | 非 tmux 服务注册（可选 pty_path） | `ipc_register` (非 tmux 环境) |
| `service_heartbeat` | 服务心跳 | 自动 |

### 会话 API

| Action | 说明 | 对应 MCP 工具 |
|--------|------|--------------|
| `conversation_create` | 创建多方会话 | `conversation_create` |

### 定时调度 API

| Action | 说明 | 对应 MCP 工具 |
|--------|------|--------------|
| `ipc_schedule_cron` | 创建 cron 定时任务 | - (daemon 内部/agentctl) |
| `ipc_schedule_periodic` | 创建周期性任务 | - |
| `ipc_schedule_once` | 创建一次性定时任务 | - |
| `ipc_schedule_remove` | 删除定时任务 | - |
| `ipc_schedule_enable` | 启用/禁用定时任务 | - |
| `ipc_schedule_list` | 列出所有定时任务 | - |
| `ipc_schedule_stats` | 定时调度统计 | - |

### 业务检查 API

| Action | 说明 | 对应 MCP 工具 |
|--------|------|--------------|
| `audit_log` | 审计日志记录 | - (hooks 调用) |
| `lep_check` | LEP 权限检查 | - (hooks 调用) |
| `pre_write_check` | 文件写入前检查 | - (hooks 调用) |
| `pre_bash_check` | 命令执行前检查 | - (hooks 调用) |

### 其他 API

| Action | 说明 |
|--------|------|
| `ping` | 健康检查（返回 uptime） |
| `rag_query` | RAG 查询（未实现） |
| `register_tmux_logger` | 注册 tmux 日志记录 |

---

## 消息格式规范

### 前缀约定

所有消息内容应以 `[角色名]` 开头，便于接收方识别来源：

```
[architect] 方案评审完成，建议采用方案 B
[devops] 部署完成，0 错误，所有容器健康
[pmo] 审批通过: cxx_service v3.1 部署计划
[qa] 测试报告: 12/12 用例通过，0 failures
[frontdesk] 用户消息: 请检查今日日报数据
```

### 优先级

| 优先级 | 响应要求 | 使用场景 |
|--------|---------|---------|
| `critical` | < 30 秒 | 生产事故、资金风险、安全事件 |
| `high` | < 2 分钟 | 用户等待中、时间敏感操作 |
| `normal` | < 10 分钟 | 常规协作、信息同步 |
| `low` | 不急 | FYI 通知、非阻塞建议 |

### 消息类型 (message_type)

| 类型 | 含义 |
|------|------|
| `request` | 发起请求，期望对方回复 |
| `response` | 回复请求 |
| `final` | 最终回复，表示对话结束 |

---

## 寻址方式

`ipc_send` 的 `to` 参数支持三种格式：

| 格式 | 示例 | 说明 |
|------|------|------|
| 逻辑名 (推荐) | `"agent_system_devops"` | daemon 自动解析到在线实例 |
| 实例 ID | `"agent_system_devops@agent_system_devops:%89"` | 精确定位到具体 pane |
| tmux pane | `"tmux:%89"` | 通过 pane ID 查找 Agent |

**推荐始终使用逻辑名**。daemon 会自动查找该 Agent 的在线实例并投递。

---

## 常见使用模式

### 模式 1: 收消息 → 处理 → 回复（基础模式）

```
# 1. 收到 [IPC] 通知后拉取消息
result = ipc_recv(ack_mode="manual", max_items=10)

# 2. 遍历处理每条消息
for msg in result.messages:
    content = msg.payload.content
    sender = msg.from

    # 3. 处理并回复（必须！）
    ipc_send(
      to=sender,
      message="[devops] 已收到，Redis 状态正常，3 节点全部健康",
      message_type="response"
    )

# 4. 确认所有消息
ipc_ack(msg_ids=[msg.msg_id for msg in result.messages])
```

### 模式 2: PMO 自提醒（派任务 + 定时检查）

```
# 1. 派任务
ipc_send(to="agent_system_architect", message="[pmo] 请设计 IPC 持久化方案")

# 2. 给自己种 30 分钟后的提醒
ipc_send_delayed(to="agent_system_pmo", message="CHECK task-001", delay_seconds=1800)
```

### 模式 3: 超时保护（Frontdesk 用）

```
# 1. 转发用户请求
ipc_send(to="agent_system_devops", message="[frontdesk] 用户问: Redis 状态?", priority="high")

# 2. 种超时检查（5 分钟）
ipc_send_delayed(to="agent_system_frontdesk", message="timeout_check", delay_seconds=300)
```

### 模式 4: 审批请求

```
# Agent 需要审批时
ipc_send(to="agent_system_pmo", message='[devops] APPROVAL_REQUEST: 部署到生产', priority="high")

# PMO 审批后
ipc_send(to="agent_system_devops", message='[pmo] APPROVAL_RESPONSE: approved', message_type="response")
```

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `BRAIN_AGENT_NAME` | `claude` | Agent 逻辑名称 |
| `BRAIN_IPC_SOCKET` | `/tmp/brain_ipc.sock` | daemon Unix Socket 路径 |
| `BRAIN_IPC_NOTIFY_SOCKET` | `/tmp/brain_ipc_notify.sock` | 通知 socket 路径 |
| `BRAIN_DAEMON_AUTOSTART` | `0` | MCP Server 是否自动启动 daemon |
| `BRAIN_TMUX_NOTIFY` | `1` | daemon 是否启用 tmux/pty 推送通知 |

---

## MCP Server 配置

每个 Agent 的 `.mcp.json` 文件配置了 MCP Server：

```json
{
  "mcpServers": {
    "mcp-brain_ipc_c": {
      "command": "/brain/bin/mcp/mcp-brain_ipc_c",
      "args": [],
      "env": {
        "BRAIN_AGENT_NAME": "agent_system_devops"
      }
    }
  }
}
```

**关键配置**：`BRAIN_AGENT_NAME` 必须与 Agent 的逻辑名一致，daemon 根据此名称路由消息。

---

## 故障排查

### ipc_recv 返回 0 条消息

1. Agent 名称不匹配 — 检查 `BRAIN_AGENT_NAME` 与发送方 `to` 字段是否一致
2. Agent 未注册 — `ipc_list_agents()` 确认自己在列表中
3. 消息已被 ack — `ack_mode="auto"` 时消息收即确认

### 消息未送达目标 Agent

1. 目标 Agent 离线 — `ipc_list_agents(include_offline=true)` 检查
2. `to` 字段拼写错误
3. daemon 未运行

### 非 tmux 会话收不到推送通知

1. 检查 `ipc_list_agents` 输出中该 agent 的 `pty_path` 是否有值
2. 如果 pty_path 为空，手动 `ipc_register` 重新注册
3. 确认 pty 设备可写：`ls -la <pty_path>`

### daemon 连接失败

1. 检查 `/tmp/brain_ipc.sock` 是否存在
2. 确认 brain_ipc 进程是否运行
3. MCP Server 默认会自动启动 daemon

---

## 相关文档

- [进程管理架构](process_management.md) — brain_ipc 在系统中的层级位置
- `/brain/base/spec/policies/ipc/message_format.yaml` — 消息格式规范
- `/brain/base/spec/policies/ipc/priority.yaml` — 优先级定义
- `/brain/base/spec/policies/ipc/reliability_design.yaml` — 可靠性设计
- `/brain/base/knowledge/troubleshooting/ipc_troubleshooting.yaml` — IPC 故障排查 SOP
