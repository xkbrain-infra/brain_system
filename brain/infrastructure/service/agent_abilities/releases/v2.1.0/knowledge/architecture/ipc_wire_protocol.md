# IPC Daemon Wire Protocol Reference

> brain_ipc daemon 的完整 wire protocol 文档。
> 适用于需要直接连接 daemon socket 的独立服务开发。
> Agent 通过 MCP 工具间接使用 IPC 的，请参考 `ipc_guide.md`。

---

## 1. 传输层

| 属性 | 值 |
|------|-----|
| Socket 类型 | Unix domain socket, `SOCK_STREAM` |
| 主 socket | `/tmp/brain_ipc.sock` |
| 通知 socket | `/tmp/brain_ipc_notify.sock`（可通过 `BRAIN_IPC_NOTIFY_SOCKET` 环境变量覆盖） |
| 帧格式 | 换行分隔 JSON。每个请求以 `\n` 结尾，每个响应以 `\n` 结尾 |
| 会话模型 | 一次连接一个请求：connect → send JSON\n → read JSON\n → close |
| 缓冲区上限 | 65536 字节（请求和响应） |
| 编码 | UTF-8 |

---

## 2. Wire 格式

### 请求信封

```json
{"action": "<action_string>", "data": { ... }}\n
```

- `action`（string，必须）：处理器标识
- `data`（object，必须）：action 特定参数

### 成功响应

```json
{"status": "ok", ...action_specific_fields...}\n
```

### 错误响应

```json
{"status": "error", "message": "<原因>"}\n
```

---

## 3. 完整 Action 列表

### 核心通信

| Action | 说明 |
|--------|------|
| `ping` | 存活检查 |
| `ipc_send` | 发送消息 |
| `ipc_recv` | 接收消息 |
| `ipc_ack` | 确认消息 |
| `ipc_send_delayed` | 延迟发送 |
| `ipc_status` | daemon 统计信息 |
| `conversation_create` | 创建会话 |

### 注册与发现

| Action | 说明 |
|--------|------|
| `agent_register` | 注册 tmux agent |
| `agent_heartbeat` | agent 心跳 |
| `agent_list` | 列出所有 agent |
| `agent_unregister` | 注销 agent |
| `service_register` | 注册服务（无需 tmux） |
| `service_heartbeat` | 服务心跳 |
| `service_list` | 列出服务 |
| `registry_search` / `search` | 模糊搜索 registry |

### 调度器

| Action | 说明 |
|--------|------|
| `ipc_schedule_cron` | Cron 定时任务 |
| `ipc_schedule_periodic` | 周期任务 |
| `ipc_schedule_once` | 一次性定时 |
| `ipc_schedule_remove` | 移除定时任务 |
| `ipc_schedule_enable` | 启用/禁用定时 |
| `ipc_schedule_list` | 列出定时任务 |
| `ipc_schedule_stats` | 调度器统计 |

### Hooks/检查（轻量 stub）

| Action | 说明 |
|--------|------|
| `audit_log` | 记录工具事件 |
| `lep_check` | LEP gate 检查（当前总是通过） |
| `pre_write_check` | 写入路径保护检查 |
| `pre_bash_check` | 删除命令警告 |

---

## 4. 常用 Action 详解

### 4.1 ping

**请求：**
```json
{"action": "ping", "data": {}}
```

**响应：**
```json
{"status": "ok", "pong": true, "uptime": 3742, "version": "2.0"}
```

### 4.2 ipc_send

**请求：**
```json
{
  "action": "ipc_send",
  "data": {
    "from": "agent-system_pmo",
    "to": "agent-system_dev",
    "payload": {"task": "implement feature X"},
    "message_type": "request",
    "conversation_id": "conv-abc123",
    "trace_id": "trace-xyz",
    "msg_id": "custom-id",
    "ttl_seconds": 3600,
    "max_attempts": 3
  }
}
```

| 参数 | 必须 | 默认 | 说明 |
|------|------|------|------|
| `to` | 是 | — | 目标名称、instance_id 或 `tmux:%pane` |
| `from` | 否 | — | 发送方（自动心跳） |
| `payload` | 否 | `{}` | 消息体 |
| `message_type` | 否 | `"request"` | `request` / `response` / `final` |
| `conversation_id` | 否 | — | 会话 ID |
| `trace_id` | 否 | — | 追踪 ID |
| `msg_id` | 否 | 自动生成 | 客户端去重 ID |
| `ttl_seconds` | 否 | 0 | 过期时间（0=不过期） |
| `max_attempts` | 否 | 5 | 最大重试次数 |

**响应：**
```json
{
  "status": "ok",
  "msg_id": "a3f8c2d14e91",
  "to": "agent-system_dev@brain_system:%5",
  "conversation_id": "conv-abc123",
  "queued_at": 1740220801
}
```

**副作用：**
1. 消息入队到目标 agent 的消息队列
2. notify socket 广播 `ipc_message` 事件
3. 若目标有 tmux_pane，发送 tmux 推送通知

### 4.3 ipc_recv

**请求：**
```json
{
  "action": "ipc_recv",
  "data": {
    "agent": "agent-system_dev",
    "conversation_id": "conv-abc123"
  }
}
```

| 参数 | 必须 | 说明 |
|------|------|------|
| `agent` | 是 | 逻辑名或 instance_id |
| `conversation_id` | 否 | 按会话过滤 |

**响应：**
```json
{
  "status": "ok",
  "messages": [
    {
      "msg_id": "a3f8c2d14e91",
      "from": "agent-system_pmo",
      "to": "agent-system_dev@brain_system:%5",
      "conversation_id": "conv-abc123",
      "message_type": "request",
      "trace_id": null,
      "ts": 1740220801,
      "attempt": 0,
      "max_attempts": 5,
      "ttl_seconds": 0,
      "expires_at": 0,
      "payload": {"task": "implement feature X"}
    }
  ],
  "count": 1
}
```

### 4.4 ipc_ack

**请求：**
```json
{
  "action": "ipc_ack",
  "data": {
    "agent": "agent-system_dev",
    "msg_ids": ["a3f8c2d14e91", "b9e2a1f03c44"]
  }
}
```

**响应：**
```json
{"status": "ok", "acked": 2, "missing": []}
```

### 4.5 service_register

**请求：**
```json
{
  "action": "service_register",
  "data": {
    "service_name": "service-timer",
    "metadata": {"version": "1.2.0"}
  }
}
```

**响应：**
```json
{"status": "ok", "service": "service-timer", "pty_path": "/dev/pts/4", "registered_at": 1740220800}
```

> daemon 通过 `SO_PEERCRED` 自动检测调用进程的 PTY。

### 4.6 ipc_send_delayed

**请求：**
```json
{
  "action": "ipc_send_delayed",
  "data": {
    "from": "agent-system_pmo",
    "to": "agent-system_dev",
    "payload": {"reminder": "standup in 5 minutes"},
    "delay_seconds": 300,
    "message_type": "response"
  }
}
```

| 参数 | 必须 | 说明 |
|------|------|------|
| `to` | 是 | 目标 |
| `delay_seconds` | 是 | 延迟秒数（1-86400） |

**响应：**
```json
{"status": "scheduled", "msg_id": "7f4a9c01be23", "send_at": 1740221101}
```

> 注意：响应 status 是 `"scheduled"` 而非 `"ok"`。

### 4.7 conversation_create

**请求：**
```json
{
  "action": "conversation_create",
  "data": {
    "participants": "agent-system_pmo,agent-system_dev",
    "metadata": {"topic": "BS-050"}
  }
}
```

`participants` 接受逗号分隔字符串或 JSON 数组。最少 2 个参与者。

**响应：**
```json
{"status": "ok", "conversation_id": "conv-a1b2c3d4", "participants": "agent-system_pmo,agent-system_dev"}
```

---

## 5. Notify Socket 推送协议

### 用途

MCP server 或 Python 服务保持长连接到 notify socket，接收实时消息事件，避免轮询。

### 连接模型

- Unix domain socket, `SOCK_STREAM`
- 客户端连接后保持打开，服务端推送换行分隔 JSON 事件
- 最大 128 个并发客户端
- 断线后建议自动重连（延迟 2s）

### 事件格式

```json
{
  "event": "ipc_message",
  "msg_id": "a3f8c2d14e91",
  "to": "agent-system_dev@brain_system:%5",
  "to_raw": "agent-system_dev",
  "from": "agent-system_pmo",
  "conversation_id": "conv-abc123",
  "ts": 1740220801
}
```

### 触发时机

1. `ipc_send` — 即时消息投递
2. `ipc_send_delayed` — 延迟到期投递
3. 调度器定时任务触发

---

## 6. Instance ID 格式

```
name@session:pane
```

示例：`agent-system_dev@brain_system:%5`

`to` 字段接受三种格式：
1. 逻辑名：`"agent-system_dev"`
2. 完整 instance_id：`"agent-system_dev@brain_system:%5"`
3. Tmux pane 快捷：`"tmux:%5"`

---

## 7. 关键常量

| 常量 | 值 | 说明 |
|------|-----|------|
| `BUFFER_SIZE` | 65536 | 请求/响应最大字节 |
| `MAX_AGENT_NAME` | 64 | agent 名称最大字符 |
| `MAX_MSG_ID` | 32 | 消息 ID 最大字符 |
| `DEFAULT_MAX_ATTEMPTS` | 5 | 默认重试次数 |
| `DEFAULT_ACK_TIMEOUT` | 60s | 确认超时 |
| `HEARTBEAT_TIMEOUT` | 300s | 心跳超时（离线判定） |
| `MAX_AGENTS` | 256 | 最大 agent 数 |
| `MAX_QUEUES` | 256 | 最大消息队列数 |
| `TMUX_DISCOVERY_INTERVAL` | 2s | tmux 自动发现间隔 |

---

## 版本

- 文档版本：1.0
- 创建日期：2026-02-22
