# 进程管理架构

> Brain 系统进程启动层级与生命周期管理

## 概述

Brain 系统采用分层进程管理架构：

| 层级 | 组件 | 职责 |
|------|------|------|
| L0 | supervisord | 容器 init 进程 (PID 1) |
| L1 | brain_ipc, brain-agentctl, sshd... | 基础服务 |
| L2 | brain-agentctl | Agent 编排 |
| L3 | claude, codex | 工作 Agent (tmux) |

## 架构图

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Container                     │
├─────────────────────────────────────────────────────────┤
│  L0: supervisord (PID 1)                                │
│       │                                                 │
│       ├── L1: brain_ipc      [IPC 基础设施]          │
│       │        └── /tmp/brain_ipc.sock               │
│       │                                                 │
│       ├── L1: brain-agentctl [Agent 编排]           │
│       │        │                                        │
│       │        └── L3: tmux sessions                    │
│       │             ├── claude_common  (claude)         │
│       │             ├── codex_common   (codex)          │
│       │             └── codex_xkquant  (按需)           │
│       │                                                  │
│       ├── L1: backend           [Web API]               │
│       ├── L1: frontend          [Web UI]                │
│       └── L1: sshd              [SSH]                   │
└─────────────────────────────────────────────────────────┘
```

## 启动顺序

1. **supervisord** 启动 (PID 1)
2. **brain_ipc** 启动 (priority=10)
3. **brain-agentctl** 启动 (priority=20, 等待 brain_ipc socket 就绪)
4. **backend/frontend/sshd** 启动
5. **brain-agentctl** 根据 `agents_registry.yaml` 启动 claude/codex

## 关键组件

### L0: supervisord

- **配置**: `/etc/supervisor/conf.d/supervisord.conf`
- **职责**: 启动和监控所有 L1 服务，进程崩溃自动重启

### L1: brain_ipc (C 实现)

- **命令**: `/brain/infrastructure/service/brain_ipc/bin/current/brain_ipc`
- **职责**:
  - Unix socket 通信 (`/tmp/brain_ipc.sock`)
  - Agent 注册表
  - 消息队列 (ACK/重试/死信)
  - 审计日志
  - Tmux 发现

### L1: brain-agentctl (Python)

- **命令**: `python3 -m brain-agentctl.services.brain-agentctl`
- **职责**:
  - 消息路由 (Telegram → Agent)
  - Agent 生命周期管理 (启动/停止/重启)
  - 健康检查
  - 命令处理 (`/status`, `/help` 等)
- **依赖**: brain_ipc

### L3: 工作 Agent

- **管理方式**: tmux session
- **注册表**: `/brain/groups/org/brain_system/projects/brain-agentctl/config/agents_registry.yaml`

| Agent | tmux session | 启动命令 |
|-------|--------------|----------|
| claude | claude_common | `claude --resume` |
| codex | codex_common | `codex --resume` |
| codex_xkquant | codex_xkquant | `codex --resume` (按需) |

## Agent Context 监控

agentctl 提供 `/context` 命令，可查询所有在线 Agent 的 context 窗口剩余百分比。

**原理**: 通过 `brain_tmux_api capture-pane` 抓取每个 agent 的 tmux 状态栏文本，解析两种 CLI 格式：

| CLI | 状态栏格式 | 解析结果 |
|-----|-----------|----------|
| Claude Code | `95% context left` | 剩余 95% |
| Codex | `Context: 40.0% used` | 剩余 60% |

**使用**: 通过 Telegram 发送 `/context`，或在 agentctl 内部调用 `CommandHandler._handle_context()`。

**注意**: 无 tmux session 的服务（如 service_timer）不会被查询；新建会话或未匹配格式显示为 N/A。

## 关键配置文件

| 文件 | 用途 |
|------|------|
| `/etc/supervisor/conf.d/supervisord.conf` | L0/L1 进程配置 |
| `/brain/groups/.../config/agents_registry.yaml` | L3 Agent 清单 |

## FAQ

### Q: brain-agentctl 由谁启动？

**A**: 由 supervisord 启动，不是由自己或其他 agent 启动。

### Q: 为什么 agents_registry.yaml 不包含 orchestrator？

**A**: orchestrator 是 L1 服务，由 supervisord 管理；registry 只包含 L3 agent，避免自引用的"鸡生蛋"问题。

### Q: brain_ipc 和 brain-agentctl 的关系？

**A**:
- brain_ipc 是 **IPC 基础设施**，提供消息传递能力
- brain-agentctl 是 **业务层**，使用 daemon 的 IPC 能力来管理 agent

## 相关文档

- `/brain/base/spec/core/architecture.yaml`
- `/brain/base/spec/policies/agents/agent_protocol.yaml`
