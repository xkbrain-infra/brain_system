# AgentCTL - 统一 Agent 控制工具

## 概述

`agentctl` 是统一的 agent 管理工具，提供两种模式：
- **CLI 模式**：直接操作 tmux 会话（本地管理）
- **Service 模式**：IPC daemon 服务（接受远程消息）

## 安装

工具位置：`/brain/infrastructure/service/service-agentctl/bin/agentctl`

建议创建软链接到系统路径：
```bash
ln -sf /brain/infrastructure/service/service-agentctl/bin/agentctl /usr/local/bin/agentctl
```

## CLI 模式

### 列出 Agents
```bash
agentctl list
```
显示所有配置的 agents 及其运行状态。

### 查看在线状态
```bash
agentctl online
```
显示通过 IPC daemon 注册的在线 agents。

### 启动 Agents
```bash
# Dry-run（预览）
agentctl start agent_name

# 实际执行
agentctl start --apply agent_name

# 启动所有
agentctl start --apply all
```

### 停止 Agents
```bash
# 停止单个
agentctl stop --apply agent_name

# 停止所有
agentctl stop --apply all
```

### 重启 Agents
```bash
agentctl restart --apply agent_name
```

## Service 模式

### 启动 IPC 守护进程
```bash
agentctl serve
```

该模式会：
- 监听 IPC 消息队列
- 路由消息到目标 agents
- 管理 agent 生命周期
- 提供健康监控
- 处理系统命令

### 环境变量
```bash
# 配置目录
export AGENTCTL_CONFIG_DIR=/path/to/config

# Daemon socket
export BRAIN_IPC_SOCKET=/tmp/brain_ipc.sock
```

## 配置

### 配置文件位置
默认：`/brain/groups/org/brain_system/projects/agent_orchestrator/config/`

包含：
- `agents_registry.yaml` - Agent 配置和注册表
- `routing_table.yaml` - 消息路由规则
- `whitelist.yaml` - 权限白名单

### agents_registry.yaml 格式
```yaml
groups:
  brain_system:
    - name: agent_system_pmo
      tmux_session: agent_system_pmo
      agent_type: claude
      cwd: /brain/groups/org/brain_system/agents/agent_system_pmo
      cli_args:
        - --dangerously-skip-permissions
      status: active
```

## Python vs C 实现

**Python 实现**（本工具）：
- `/brain/infrastructure/service/service-agentctl/releases/current/bin/agentctl`
- 功能完整，包含 CLI 和 Service 模式

**C 实现**：
- `/brain/infrastructure/engine/bin/brain_client` - IPC 客户端
- `/brain/infrastructure/engine/bin/audit_hook` - 审计钩子
- `/brain/infrastructure/engine/bin/lep_check` - LEP 检查

## 架构

```
agentctl (统一入口)
├── CLI 模式
│   ├── list - 读取配置，检查 tmux 状态
│   ├── online - 查询 IPC daemon
│   ├── start - 创建 tmux 会话
│   ├── stop - 终止 tmux 会话
│   └── restart - 停止 + 启动
│
└── Service 模式 (serve)
    ├── AgentCtlService (主服务)
    ├── Router (消息路由)
    ├── Dispatcher (消息分发)
    ├── Launcher (启动器)
    ├── Provisioner (配置器)
    └── CommandHandler (命令处理)
```

## 常见用法

### 场景 1：本地开发管理 agents
```bash
# 查看状态
agentctl list

# 启动特定 agent
agentctl start --apply agent_system_pmo

# 重启所有 agents
agentctl restart --apply all
```

### 场景 2：生产环境运行 Service
```bash
# 在 tmux 会话中启动
tmux new-session -d -s service-agentctl \
  "agentctl serve"
```

### 场景 3：检查系统状态
```bash
# 查看配置的 agents
agentctl list

# 查看实际在线的 agents（通过 IPC）
agentctl online
```

## 故障排查

### 配置文件找不到
```bash
# 指定配置目录
agentctl --config-dir /path/to/config list
```

### Daemon 连接失败
```bash
# 检查 daemon 是否运行
ps aux | grep brain_ipc

# 检查 socket
ls -la /tmp/brain_ipc.sock
```

### Agent 启动失败
```bash
# 检查 tmux 会话
tmux list-sessions

# 查看 agent 日志
tmux attach -t agent_name
```

## 开发

### 目录结构
```
/brain/infrastructure/service/service-agentctl/
├── bin/agentctl           # 主程序
├── config/                # 配置加载
├── core/                  # 核心逻辑
├── handlers/              # 命令处理
└── services/              # 服务组件
```

### 添加新功能
1. CLI 命令：在 `bin/agentctl` 中添加子命令
2. Service 功能：在 `services/` 中添加组件

## 更多信息

- IPC 协议：`/brain/infrastructure/engine/docs/agent_ipc_guide.md`
- Agent 开发：`/brain/base/spec/policies/agents/agent_protocol.yaml`
- 配置规范：`/brain/base/spec/core/architecture.yaml`
