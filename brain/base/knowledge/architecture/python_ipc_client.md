# Python 服务接入 IPC 指南

> 面向开发独立 Python 服务的 agent/开发者。
> 如果你是在 agent 会话中使用 IPC，请看 `ipc_guide.md`。
> 如果你需要 wire protocol 细节，请看 `ipc_wire_protocol.md`。

---

## 1. 核心概念

```
Agent (tmux session)          独立 Python 服务
+----------------+            +--------------------+
| Agent CLI      |            | Python process     |
|   ^ stdio      |            |                    |
| MCP Server     |            | DaemonClient       |
| (brain_ipc_c)  |            |   ^ socket         |
|   ^ socket     |            +--------+-----------+
+------+---------+                     |
       |                               |
       v                               v
  /tmp/brain_ipc.sock <--- brain_ipc daemon ---> /tmp/brain_ipc_notify.sock
```

**Agent** 通过 MCP Server 桥接间接使用 IPC。
**独立服务** 直接连接 daemon socket，使用 `DaemonClient` 类。

---

## 2. DaemonClient 快速上手

### 2.1 导入

```python
import importlib.util, os, sys

# 标准导入路径
_spec = importlib.util.spec_from_file_location(
    "daemon_client",
    "/brain/infrastructure/service/utils/ipc/bin/current/ipc_client.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
DaemonClient = _mod.DaemonClient
```

或者如果 `releases/v1.0.0` 可用（包含 NotifyClient）：

```python
_spec = importlib.util.spec_from_file_location(
    "daemon_client",
    "/brain/infrastructure/service/utils/ipc/releases/v1.0.0/bin/daemon_client.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
DaemonClient = _mod.DaemonClient
NotifyClient = _mod.NotifyClient
```

### 2.2 基本操作

```python
SOCKET = os.environ.get("DAEMON_SOCKET", "/tmp/brain_ipc.sock")
NOTIFY_SOCKET = os.environ.get("BRAIN_IPC_NOTIFY_SOCKET", "/tmp/brain_ipc_notify.sock")
client = DaemonClient(SOCKET)

# 注册服务
client.register_service("service-my_service", metadata={"version": "1.0"})

# 发送消息
client.send(
    from_agent="service-my_service",
    to_agent="agent_system_pmo",
    payload={"type": "TASK_STATUS", "task_id": "T001", "status": "completed"}
)

# 接收消息
messages = client.recv("service-my_service")
for msg in messages.get("messages", []):
    print(f"From: {msg['from']}, Payload: {msg['payload']}")

# 确认消息
msg_ids = [m["msg_id"] for m in messages.get("messages", [])]
if msg_ids:
    client.ack("service-my_service", msg_ids)

# 心跳
client.service_heartbeat("service-my_service")
```

---

## 3. 事件驱动服务模板

### 3.1 异步服务（推荐）

```python
import asyncio
import importlib.util
import os

# 导入
_spec = importlib.util.spec_from_file_location(
    "daemon_client",
    "/brain/infrastructure/service/utils/ipc/releases/v1.0.0/bin/daemon_client.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
DaemonClient = _mod.DaemonClient
NotifyClient = _mod.NotifyClient

SERVICE_NAME = "service-my_service"
SOCKET = os.environ.get("DAEMON_SOCKET", "/tmp/brain_ipc.sock")
client = DaemonClient(SOCKET)

async def heartbeat_loop():
    """Heartbeat every 60s"""
    while True:
        try:
            client.service_heartbeat(SERVICE_NAME)
        except Exception as e:
            print(f"Heartbeat error: {e}")
        await asyncio.sleep(60)

async def message_loop():
    """Listen notify socket, pull messages on event"""
    notify = NotifyClient(SERVICE_NAME)
    async for event in notify.listen():
        try:
            result = client.recv(SERVICE_NAME)
            for msg in result.get("messages", []):
                await handle_message(msg)
                client.ack(SERVICE_NAME, [msg["msg_id"]])
        except Exception as e:
            print(f"Message handling error: {e}")

async def handle_message(msg):
    """Handle a single message - implement business logic here"""
    payload = msg.get("payload", {})
    print(f"Received from {msg['from']}: {payload}")
    
    # Reply to sender
    client.send(
        from_agent=SERVICE_NAME,
        to_agent=msg["from"],
        payload={"type": "ACK", "original_msg_id": msg["msg_id"]},
        conversation_id=msg.get("conversation_id")
    )

async def main():
    client.register_service(SERVICE_NAME)
    print(f"{SERVICE_NAME} registered, starting event loop...")
    await asyncio.gather(heartbeat_loop(), message_loop())

if __name__ == "__main__":
    asyncio.run(main())
```

### 3.2 同步服务（简单场景）

```python
import time
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "daemon_client",
    "/brain/infrastructure/service/utils/ipc/bin/current/ipc_client.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
DaemonClient = _mod.DaemonClient

SERVICE_NAME = "service-simple"
client = DaemonClient("/tmp/brain_ipc.sock")
client.register_service(SERVICE_NAME)

while True:
    client.service_heartbeat(SERVICE_NAME)
    result = client.recv(SERVICE_NAME)
    
    for msg in result.get("messages", []):
        handle(msg)
        client.ack(SERVICE_NAME, [msg["msg_id"]])
    
    time.sleep(5)  # Polling (not recommended, use NotifyClient instead)
```

---

## 4. 常见错误

### 4.1 尝试调用 MCP 工具

```python
# WRONG: mcp_ipc module does not exist
from mcp_ipc import ipc_send, ipc_recv

# WRONG: MCP tools cannot be called from Python
import mcp
mcp.tools.call("ipc_send", ...)
```

MCP 工具仅在 agent CLI 会话内可用（通过 stdio JSON-RPC）。独立服务必须直接连接 daemon socket。

### 4.2 忘记注册

```python
# WRONG: recv without register, daemon doesn't know you
result = client.recv("service-unregistered")

# CORRECT: register first
client.register_service("service-my_service")
result = client.recv("service-my_service")
```

### 4.3 忘记心跳

daemon 的 HEARTBEAT_TIMEOUT 是 300 秒。超过 5 分钟没心跳，daemon 判定服务离线。

---

## 5. Supervisord 配置模板

```ini
[program:my_service]
command=python3 /brain/infrastructure/service/my_service/src/main.py
environment=DAEMON_SOCKET="/tmp/brain_ipc.sock",PYTHONUNBUFFERED="1"
directory=/brain/infrastructure/service/my_service
autostart=true
autorestart=true
startsecs=3
stopasgroup=true
killasgroup=true
stdout_logfile=/xkagent_infra/runtime/logs/my_service.out.log
stderr_logfile=/xkagent_infra/runtime/logs/my_service.err.log
stdout_logfile_maxbytes=10MB
stderr_logfile_maxbytes=10MB
```

> **必须设置**：PYTHONUNBUFFERED=1（实时日志）、stopasgroup=true + killasgroup=true（防止子进程孤儿化）、stdout_logfile_maxbytes（防止磁盘溢出）。

---

## 6. 参考实现

| 服务 | 复杂度 | 路径 | 特点 |
|------|--------|------|------|
| supervisor_bridge | 最简 | `infrastructure/service/supervisor_bridge/` | 同步，最小 IPC 服务 |
| timer | 中等 | `infrastructure/service/timer/releases/v1.0.0/src/timer/` | 异步，cron + DaemonClient + NotifyClient |
| dashboard | 复杂 | `infrastructure/service/dashboard/releases/v1.0.0/src/` | 异步，数据采集 + SQLite + 告警 + FastAPI |
| agent_vectordb | 中等 | `infrastructure/service/agent_vectordb/` | 异步，IPC service + MCP server 双模 |

---

## 版本

- 文档版本：1.0
- 创建日期：2026-02-22
