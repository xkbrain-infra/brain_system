# IPC 自动唤醒机制设计

- **ID**: ADR-IPC-AUTO-WAKE
- **状态**: Approved
- **作者**: agent-system_architect
- **日期**: 2026-03-08
- **审批**: PMO 已批准 (2026-03-08)

## 1. 问题陈述

当前所有 Agent 使用 Claude Code CLI 的被动监听模式（passive listen）。Agent 空闲时收到 IPC 消息，IPC daemon 通过 `brain_tmux_send` 注入 `[IPC] New message from...` 通知文本到 tmux pane，但存在以下问题：

1. **Agent 空闲时**：通知文本被注入并自动提交（`--double-enter`），但 Claude Code 将其视为用户输入。Agent 正确响应后会完成当前 turn，**回到空闲等待状态**。如果后续有新消息到达，需要再次注入——这部分已经工作。
2. **Agent 工作中**：通知被注入到当前输入缓冲区，可能与 Agent 正在执行的操作产生干扰（文本混入命令、触发意外提交等）。
3. **PMO 的 `ipc_send_delayed` 自提醒**：延迟消息到达时，如果 Agent 忙碌，通知会丢失或被忽略。
4. **Agent 完成任务后不检查 IPC 队列**：Agent 完成当前工作后直接进入空闲状态，不会主动检查是否有新消息积压。
5. **无 token 预算限制**：任何轮询方案都可能导致无限 token 消耗。

## 2. 现有架构分析

### 2.1 消息投递链路（已工作）

```
Sender Agent                IPC Daemon              Target Agent (tmux pane)
    |                          |                          |
    |-- ipc_send(to=X) ------>|                          |
    |                          |-- msgqueue_send() ------>| (队列入队)
    |                          |-- notify_broadcast() --->| (notify socket)
    |                          |-- tmux_notify() -------->| (fork brain_tmux_send)
    |                          |                          |
    |                          |      brain_tmux_send:    |
    |                          |      1. detect TUI type  |
    |                          |      2. send-keys -l text|
    |                          |      3. C-m (Enter)      |
    |                          |      4. C-m x2 (double)  |
    |                          |                          |
    |                          |      Claude Code sees:   |
    |                          |      "[IPC] New message   |
    |                          |       from X (msg_id=Y)" |
    |                          |      → Agent calls       |
    |                          |        ipc_recv()        |
```

### 2.2 可利用的 Claude Code Hook 事件

| Hook | 触发时机 | 能力 |
|------|---------|------|
| `Stop` | Agent 完成响应，即将停止 | **可阻止停止**，注入继续工作的理由 |
| `Notification(idle_prompt)` | Agent 空闲时发送通知 | 注入 `additionalContext` |
| `UserPromptSubmit` | 用户/系统提交 prompt | 注入 `additionalContext`（不可改写 prompt） |
| `SessionStart(resume)` | 会话恢复时 | 注入 `additionalContext` |

### 2.3 关键约束

- **不魔改 Claude Code CLI 本身**
- **不引入无限轮询**（token 预算有限）
- **兼容现有 tmux + IPC daemon 架构**
- **Agent 忙碌时不被打断**

## 3. 方案对比

### 方案 A: Stop Hook 拦截 + IPC 队列检查（推荐）

**核心思路**: 在 Agent 每次完成响应（即将停止/空闲）时，通过 `Stop` hook 检查 IPC 队列，如有待处理消息则阻止停止并注入处理指令。

```
Agent 完成任务 → Stop hook 触发
                    |
                    ├── 查询 IPC daemon 队列
                    │   (socket 连接 /tmp/brain_ipc.sock)
                    │
                    ├── 有消息? ──yes──> 输出 {"decision":"block","reason":"[IPC] N条待处理消息..."}
                    │                    Agent 继续工作，调用 ipc_recv()
                    │
                    └── 无消息? ──no───> exit 0 (允许停止，Agent 进入空闲)
                                         此时 tmux push 通知恢复为唤醒机制
```

**数据流**:

```
┌────────────────── Claude Code Session ──────────────────┐
│                                                         │
│  Agent 工作中... ─完成─> [Stop Hook]                     │
│                           │                             │
│                    ┌──────┴───────┐                     │
│                    │ stop_guard.py │                     │
│                    │              │                     │
│                    │ connect to   │                     │
│                    │ brain_ipc.sock│                     │
│                    │ → ipc_recv   │                     │
│                    │   (peek mode)│                     │
│                    │              │                     │
│                    │ count > 0?   │                     │
│                    │  Y: block    │                     │
│                    │  N: pass     │                     │
│                    └──────────────┘                     │
│                                                         │
│  Agent 空闲 ←── tmux push 通知唤醒（现有机制不变）        │
└─────────────────────────────────────────────────────────┘
```

**改动范围**:

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `brain/infrastructure/service/agent_abilities/bin/hooks/2.1.0/ipc/stop_guard.py` | **新建** | Stop hook 处理逻辑，查询 IPC 队列 |
| `brain/infrastructure/service/agent_abilities/bin/hooks/2.1.0/stop_hook` | **新建** | Stop hook 入口脚本（与其他 hook 入口一致的 bootstrap 模式） |
| `brain/infrastructure/service/brain_ipc/src/brain_ipc.c` | **修改** | 添加 `ipc_peek` action：只查询队列消息数量，不出队不改变状态 |
| `brain/infrastructure/service/agent_abilities/src/base/mcp/brain_ipc_c/main.c` | **可选修改** | 添加 `ipc_peek` MCP tool（非必需，stop_guard 可直接 socket 查询） |
| `groups/**/agents/**/.claude/settings.local.json` | **修改** | 所有 agent 的 settings 添加 Stop hook 配置 |
| `brain/infrastructure/service/agentctl/config/config_generator.py` | **修改** | settings 生成模板添加 Stop hook |

**优点**:
- **零额外 token 消耗**: hook 是外部 Python 脚本，不消耗 LLM token
- **精确时机**: 恰好在 Agent 完成任务后、进入空闲前触发
- **不打断工作中的 Agent**: 仅在 Stop 时触发，Agent 忙碌时完全不受影响
- **与现有 tmux push 互补**: Stop hook 处理"任务间"消息，tmux push 处理"空闲时"消息
- **无循环风险**: Agent 处理完 IPC 消息后再次触发 Stop hook，如果没有新消息则正常停止

**缺点**:
- 需要修改 IPC daemon 添加 peek action（或 stop_guard 直接用现有 ipc_recv + count_only 模式）
- Stop hook 有 5s timeout 限制，socket 查询需要快速完成

**防无限循环**:
- stop_guard.py 维护一个本地计数器文件 `/tmp/ipc_stop_guard_{agent}.count`
- 连续 Stop hook 拦截超过 10 次，强制放行（避免消息处理异常导致死循环）
- 每次成功放行重置计数器

---

### 方案 B: Notification Hook + UserPromptSubmit 双重注入

**核心思路**: 利用 `Notification(idle_prompt)` hook 在 Agent 空闲收到通知时检查 IPC 队列，以及利用 `UserPromptSubmit` hook 在每次接收 prompt 时附加 IPC 状态。

```
Notification(idle_prompt) → check IPC queue → additionalContext: "你有 N 条消息"
UserPromptSubmit          → check IPC queue → additionalContext: "处理完当前请求后检查 IPC"
```

**改动范围**:

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `brain/infrastructure/service/agent_abilities/bin/hooks/2.1.0/session/handler.py` | **修改** | `handle_user_prompt_submit()` 添加 IPC 队列检查 |
| `brain/infrastructure/service/agent_abilities/bin/hooks/2.1.0/ipc/notification_handler.py` | **新建** | Notification hook 处理 |
| `brain/infrastructure/service/agent_abilities/bin/hooks/2.1.0/notification_hook` | **新建** | Notification hook 入口 |
| `groups/**/agents/**/.claude/settings.local.json` | **修改** | 添加 Notification hook 配置 |
| `brain/infrastructure/service/brain_ipc/src/brain_ipc.c` | **修改** | 同方案 A，添加 peek action |

**优点**:
- 不依赖 Stop hook（较新的 Claude Code 功能）
- 双重保障（两个时机都能注入提示）

**缺点**:
- **依赖 Claude Code 主动发送 idle_prompt 通知**（时机不可控，不保证一定触发）
- **UserPromptSubmit 每次都触发**，即使是普通用户操作也会查 IPC 队列（不必要的开销）
- **仅注入 additionalContext，不能阻止 Agent 停止**：Agent 看到提示后可能仍然停止
- **可靠性低于方案 A**：依赖 Agent 的 LLM 理解力来处理 context 中的提示

---

### 方案 C: 外部 Watcher Daemon + claude CLI 注入

**核心思路**: 独立运行一个 watcher daemon，持续监听 IPC notify socket，当目标 agent 有消息时通过 `claude -r <session> -p "..."` 注入 prompt。

```
┌─────────────────────────────────────────┐
│         ipc_wake_daemon (Python)         │
│                                         │
│  NotifyClient → 监听 notify socket      │
│                   │                     │
│   收到消息事件 → 判断目标 agent 状态     │
│                   │                     │
│   Agent 空闲? → claude -r SESSION -p    │
│                  "[IPC] check inbox"     │
│   Agent 忙碌? → 写入待唤醒队列          │
│                  (等 agent stop 后再注入) │
└─────────────────────────────────────────┘
```

**改动范围**:

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `brain/infrastructure/service/ipc_wake_daemon/src/watcher.py` | **新建** | 唤醒守护进程 |
| `brain/infrastructure/service/ipc_wake_daemon/config/wake.service` | **新建** | systemd 服务 |
| `brain/infrastructure/service/ipc_wake_daemon/bin/ipc_wake` | **新建** | 入口脚本 |

**优点**:
- 完全外部化，不依赖 Claude Code hooks
- 可以精确控制唤醒时机

**缺点**:
- **引入新的 daemon 进程**：增加运维复杂度
- **需要获取 Claude Code session ID**：`claude -r` 需要 session ID，获取方式不稳定
- **claude CLI 注入可能创建新会话**而非恢复现有会话
- **与现有 tmux push 功能重叠**：本质是 tmux push 的另一种实现
- **改动范围最大**：需要新建独立服务

## 4. 推荐方案

**推荐方案 A: Stop Hook 拦截 + IPC 队列检查**

理由：
1. **最小改动原则**: 核心改动只需 1 个新 Python 文件 + settings 配置更新
2. **零 token 消耗**: hook 是外部脚本，不消耗 LLM API token
3. **精确可靠**: Stop 是确定性事件，每次 Agent 完成响应必定触发
4. **与现有机制互补**: Stop hook 负责"任务间衔接"，tmux push 负责"空闲唤醒"
5. **无侵入**: 不修改 Claude Code CLI，不引入新 daemon

### 4.1 实现细节

#### 4.1.1 stop_guard.py 核心逻辑

```python
#!/usr/bin/env python3
"""Stop Hook: 检查 IPC 队列，有消息时阻止 Agent 停止"""

import json
import os
import socket
import sys
import time

DAEMON_SOCKET = os.environ.get("BRAIN_IPC_SOCKET", "/tmp/brain_ipc.sock")
AGENT_NAME = os.environ.get("BRAIN_AGENT_NAME", "")
MAX_CONSECUTIVE_BLOCKS = 10  # 防无限循环
COUNTER_FILE = f"/tmp/ipc_stop_guard_{AGENT_NAME}.count"


def peek_ipc_queue() -> int:
    """查询 IPC 队列中待处理消息数量"""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(DAEMON_SOCKET)

        request = json.dumps({
            "action": "ipc_recv",
            "agent_name": AGENT_NAME,
            "count_only": True
        }) + "\n"
        sock.sendall(request.encode())

        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break

        sock.close()
        resp = json.loads(data.decode().strip())
        return resp.get("count", 0)
    except Exception:
        return 0


def read_counter() -> int:
    try:
        with open(COUNTER_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return 0


def write_counter(n: int):
    try:
        with open(COUNTER_FILE, "w") as f:
            f.write(str(n))
    except Exception:
        pass


def main():
    data = json.load(sys.stdin)

    # 安全阀：连续拦截过多次，强制放行
    counter = read_counter()
    if counter >= MAX_CONSECUTIVE_BLOCKS:
        write_counter(0)
        sys.exit(0)  # 放行

    pending = peek_ipc_queue()

    if pending > 0:
        write_counter(counter + 1)
        result = {
            "decision": "block",
            "reason": f"[IPC] 你有 {pending} 条待处理消息。请调用 ipc_recv() 获取并处理这些消息。"
        }
        print(json.dumps(result, ensure_ascii=False))
    else:
        write_counter(0)  # 重置计数器
        sys.exit(0)  # 放行


if __name__ == "__main__":
    main()
```

#### 4.1.2 IPC Daemon 改动：添加 count_only 支持

在 `handle_ipc_recv()` 中添加 `count_only` 参数支持：

```c
// brain_ipc.c handle_ipc_recv() 中添加:
int count_only = 0;
cJSON *co = cJSON_GetObjectItem(root, "count_only");
if (co && cJSON_IsTrue(co)) count_only = 1;

if (count_only) {
    int cnt = msgqueue_count(&g_msgqueue, resolved);
    char extra[128];
    snprintf(extra, sizeof(extra), "\"count\":%d", cnt);
    return json_ok(extra);
}
```

在 `msgqueue.c` 中添加 `msgqueue_count()`:

```c
int msgqueue_count(MsgQueue *mq, const char *agent_key) {
    // 返回指定 agent 队列中的消息数量（不出队）
    unsigned h = hash_str(agent_key) % mq->bucket_count;
    QueueBucket *b = &mq->buckets[h];
    // ... 遍历计数
}
```

#### 4.1.3 Settings 配置更新

每个 agent 的 `.claude/settings.local.json` 添加：

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/brain/infrastructure/service/agent_abilities/bin/hooks/current/stop_hook",
            "timeout": 3000,
            "description": "IPC auto-wake: check pending messages before stopping",
            "env": {
              "BRAIN_AGENT_NAME": "<agent_name>",
              "BRAIN_IPC_SOCKET": "/tmp/brain_ipc.sock"
            }
          }
        ]
      }
    ]
  }
}
```

### 4.2 完整改动清单 (G-ATOMIC)

| # | 文件 | 操作 | 具体内容 |
|---|------|------|---------|
| 1 | `/brain/infrastructure/service/agent_abilities/bin/hooks/2.1.0/ipc/stop_guard.py` | 新建 | IPC 队列检查逻辑，约 80 行 Python |
| 2 | `/brain/infrastructure/service/agent_abilities/bin/hooks/2.1.0/stop_hook` | 新建 | Hook 入口脚本，设置 HOOK_ROOT 后调用 `ipc.stop_guard.main()` |
| 3 | `/brain/infrastructure/service/agent_abilities/bin/hooks/current/stop_hook` | 符号链接 | → `../2.1.0/stop_hook` |
| 4 | `/brain/infrastructure/service/brain_ipc/src/brain_ipc.c` | 修改 | `handle_ipc_recv()` 函数添加 `count_only` 分支（约 +15 行） |
| 5 | `/brain/infrastructure/service/brain_ipc/src/msgqueue.c` | 修改 | 添加 `msgqueue_count()` 函数（约 +20 行） |
| 6 | `/brain/infrastructure/service/brain_ipc/src/msgqueue.h` | 修改 | 添加 `msgqueue_count()` 声明（+1 行） |
| 7 | `groups/**/agents/**/.claude/settings.local.json` (5 个 agent) | 修改 | hooks 部分添加 Stop hook 配置 |
| 8 | `/brain/infrastructure/service/agentctl/config/config_generator.py` | 修改 | settings 生成模板添加 Stop hook |
| 9 | `/brain/infrastructure/service/agent_abilities/bin/hooks/v2.1.0/configs/settings.roles/settings.*.json` (4 个) | 修改 | 角色 settings 模板添加 Stop hook |

### 4.3 验证步骤

1. **单元验证**: 手动向某个 agent 发送 IPC 消息，观察 agent 完成当前任务后是否自动调用 `ipc_recv()`
2. **防循环验证**: 发送一条 agent 无法处理的消息，观察 Stop hook 在 10 次拦截后是否放行
3. **并发验证**: Agent 工作中连续发送 3 条消息，观察是否都在 agent 空闲后被依次处理
4. **性能验证**: 确认 stop_guard.py socket 查询耗时 < 50ms（在 3s timeout 内）
5. **回归验证**: 确认不影响现有 tmux push 唤醒机制（Agent 空闲时仍能被 tmux notify 唤醒）

## 5. 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| Stop hook 无限循环（消息处理失败反复触发） | 中 | 高 | 计数器安全阀（MAX_CONSECUTIVE_BLOCKS=10） |
| Socket 连接 daemon 超时 | 低 | 低 | 2s timeout + 异常默认放行（return 0 = 无消息） |
| Stop hook 与 Claude Code 版本兼容性 | 低 | 中 | Stop hook 是标准 hook 事件，Claude Code 2.x 均支持 |
| IPC daemon 重启时 stop_guard 连接失败 | 低 | 低 | 异常处理中默认放行，不影响 agent 正常工作 |
| Agent 处理消息耗时过长阻塞后续消息 | 中 | 中 | 由 agent 的 CLAUDE.md 中 max_items=10 控制批量处理 |

## 6. 实施路线

```
Phase 1 (Day 1): IPC Daemon 改动
  - 添加 count_only 支持到 handle_ipc_recv()
  - 添加 msgqueue_count()
  - 编译测试

Phase 2 (Day 1-2): Stop Hook 开发
  - 实现 stop_guard.py
  - 实现 stop_hook 入口脚本
  - 本地测试

Phase 3 (Day 2): 配置部署
  - 更新 settings 模板和 config_generator
  - 更新 5 个 agent 的 settings.local.json
  - 验证所有 agent 正常启动

Phase 4 (Day 3): 集成测试
  - 执行验证步骤 1-5
  - 观察 24 小时运行稳定性
```

## 7. 未来扩展

本方案为 Phase 1。后续可考虑：
- **优先级唤醒**: Stop hook 根据消息 priority 决定是否拦截（low 优先级不拦截）
- **批量处理优化**: Stop hook 直接在 additionalContext 中注入消息摘要，减少一次 ipc_recv 调用
- **Notification hook 补充**: 作为 Stop hook 的补充，在 idle_prompt 时也检查 IPC 队列
