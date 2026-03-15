# Brain System Infrastructure Reference

> 总索引文档。所有 agent 在设计、开发新服务或集成现有服务前，**必须先查阅本文档**。
>
> 深入参考：
> - IPC wire protocol → `ipc_wire_protocol.md`
> - Python 服务接入 IPC → `python_ipc_client.md`
> - IPC 使用指南（agent 视角）→ `ipc_guide.md`

---

## 1. 服务清单

### 1.1 核心基础设施

| 服务 | 类型 | 入口 | 通信方式 | 说明 |
|------|------|------|----------|------|
| **brain_ipc** | C 二进制 | `/brain/bin/brain_ipc` | Unix socket `/tmp/brain_ipc.sock` | IPC 消息总线（主）。JSON-over-socket 协议。所有 agent 间通信经由此 daemon |
| **brain_ipc_pty** | C 二进制 | `infrastructure/service/brain_ipc_pty/` | Unix socket `/tmp/brain_ipc_pty.sock` | IPC 消息总线（PTY 变体），用于非 tmux 的 agent |

### 1.2 Supervisord 管理的服务（自启动）

| 服务 | 类型 | 端口 | 说明 |
|------|------|------|------|
| **brain_gateway** | C++ 二进制 | HTTP `8200` | 外部流量入口（Telegram→agent 路由）。连接 IPC socket |
| **health_check** | Python | HTTP `8765` | 系统健康检查端点。探测 IPC daemon + 各 service 心跳 |
| **task_manager** | C 二进制 | Health `8091` | Task/Spec SSOT 服务。处理 TASK_CREATE/UPDATE/QUERY，管理 deadline |
| **task_manager_runtime** | Python | Health `8766` | 项目 FSM 引擎（BS-025 产出，**broken: IPC 层未实现**） |
| **service_telegram_api** | Python | — | Telegram Bot 长轮询 → IPC 消息转发（支持多 bot 实例，BOT_INSTANCE=1/2） |
| ~~service-agent_gateway~~ | C 二进制 | — | agent 级消息路由网关（**已移除**，配置和二进制不存在） |
| **brain_google_api** | C 二进制 | — | Google API MCP server（stdio 模式，无 HTTP 端口，autostart=false） |

### 1.3 独立运行的服务

| 服务 | 类型 | 端口 | 说明 |
|------|------|------|------|
| **agentctl** | Python | — | Agent 生命周期管理（CLI + IPC service 模式）。注册为 `service-agentctl` |
| **timer** | Python | Health `8090` | 定时器服务。从 `timers.yaml` 加载 cron/interval 任务，注册为 `service-timer` |
| **monitor** | Python (FastAPI) | HTTP `8100` | 系统状态 API。提供 agent/IPC/daemon 统一监控 |
| **dashboard** | Python | — | agent 监控后台。定期采集状态→SQLite，异常告警→Telegram |
| **agent_vectordb** | Python | Health `8094` | 文档向量数据库查询服务。注册为 `service-agent_vectordb` |
| **supervisor_bridge** | Python | — | supervisord IPC 桥接。注册为 `service-supervisor` |
| **litellm_proxy** | Python (LiteLLM) | HTTP `8001` | OpenAI 兼容 API 代理。为 Codex agent 提供 GPT 模型 |

### 1.4 工具/库

| 名称 | 路径 | 说明 |
|------|------|------|
| **utils/ipc** | `infrastructure/service/utils/ipc/` | Python IPC 客户端库（DaemonClient / NotifyClient） |
| **utils/tmux** | `infrastructure/service/utils/tmux/` | tmux 工具（brain_tmux_api / brain_tmux_send） |
| **agent_abilities** | `infrastructure/service/agent_abilities/` | Base 构建/部署系统 + MCP server + hooks |

---

## 2. MCP Server 清单

MCP Server 是 agent 在会话中可调用的工具集。**仅在 agent 会话内可用，独立 Python/C 服务无法调用 MCP 工具。**

> **关键区分**：MCP Server 是 agent session 的 sidecar 进程，通过 stdio JSON-RPC 与 agent CLI 通信。
> 独立服务如需 IPC 通信，必须直接连接 daemon socket（见 `python_ipc_client.md`）。

| MCP Server | 二进制路径 | 工具数 | 底层服务 | 适用范围 |
|------------|-----------|--------|----------|----------|
| **mcp-brain_ipc_c** | `/brain/bin/mcp/mcp-brain_ipc_c` | 8 | brain_ipc daemon | 所有 agent（标准模板） |
| **mcp-agent_vectordb** | `/brain/bin/mcp/mcp-agent_vectordb` | 4 | service-agent_vectordb | 所有 agent |
| **mcp-brain_base_deploy** | `/brain/bin/mcp/mcp-brain_base_deploy` | 6 | agent_abilities 构建系统 | 仅 brain-manager |
| **mcp-brain_google_api** | `/brain/bin/mcp/mcp-brain_google_api` | 38 actions | Google APIs (OAuth2) | ACL 控制（需 brain_google_api service 运行） |

### 2.1 mcp-brain_ipc_c 工具列表

| 工具 | 说明 | 关键参数 |
|------|------|----------|
| `ipc_send` | 发消息给其他 agent | `to`, `message` |
| `ipc_recv` | 接收消息（支持长轮询） | `wait_seconds` (0-120) |
| `ipc_send_delayed` | 延迟发送 | `to`, `message`, `delay_seconds` (1-86400) |
| `ipc_register` | 注册为在线 | — |
| `ipc_list_agents` | 列出所有 agent | `include_offline` |
| `ipc_list_services` | 列出所有 service | `include_offline` |
| `ipc_search` | 模糊搜索 registry | `query`, `source`, `fuzzy` |
| `conversation_create` | 创建多轮会话 | `participants` |

### 2.2 mcp-agent_vectordb 工具列表

| 工具 | 说明 | 关键参数 |
|------|------|----------|
| `doc_query` | 按关键词/域/分类搜索文档 | `keyword`, `domain`, `category`, `tags` |
| `doc_get` | 按 ID 精确获取文档 | `doc_id` |
| `doc_related` | 向量相似文档 | `doc_id` |
| `doc_search` | 自然语言语义搜索 | `query` |

### 2.3 mcp-brain_base_deploy 工具列表

| 工具 | 说明 |
|------|------|
| `deploy_diff` | 查看 src 与 base 之间差异 |
| `deploy_publish` | 完整发布流水线：diff → merge → build → deploy |
| `deploy_merge` | 从 base 反向合并回 src |
| `deploy_versions` | 列出所有发布版本 |
| `deploy_rollback` | 回滚到历史版本 |
| `deploy_stats` | 生成覆盖统计 |

### 2.4 mcp-brain_google_api

单一 `google_api` 工具，通过 `action` 参数分发。支持：Gmail (6)、Drive (6)、Calendar (4)、Docs (3)、Slides (3)、Tasks (6)、Sheets (4)、People (3)、ACL (3)。

---

## 3. 技能（Skills）清单

技能是 agent 会话中通过 `/skill_name` 调用的快捷操作。

| Skill ID | 调用方式 | 说明 |
|----------|---------|------|
| `G-SKILL-ADD-AGENT` | `/add-agent [name] [group]` | 交互式添加 agent（agentctl add 包装） |
| `G-SKILL-AGENTCTL` | `/agentctl [cmd] [agents...]` | agent 生命周期管理 |
| `G-SKILL-DOC-SEARCH` | `/doc-search [query]` | 两阶段文档查找：向量搜索 → 精确读取 |
| `G-SKILL-IPC` | `/ipc [send\|recv\|search\|list]` | IPC 通信快捷操作 |
| `G-SKILL-TMUX` | `/tmux [agent_name]` | 只读查看 agent 终端 |

---

## 4. 端口与 Socket 总表

### 4.1 Unix Socket

| 路径 | 服务 | 协议 | 说明 |
|------|------|------|------|
| `/tmp/brain_ipc.sock` | brain_ipc | JSON-over-socket | 主 IPC 总线 |
| `/tmp/brain_ipc_notify.sock` | brain_ipc | Push JSON events | IPC 消息推送通知 |
| `/tmp/brain_ipc_pty.sock` | brain_ipc_pty | JSON-over-socket | PTY 变体 IPC 总线 |
| `/tmp/brain_ipc_pty_notify.sock` | brain_ipc_pty | Push JSON events | PTY 变体推送通知 |

### 4.2 HTTP 端口

| 端口 | 服务 | 用途 |
|------|------|------|
| 8001 | litellm_proxy | OpenAI 兼容 API（`/v1`） |
| 8090 | timer | 健康检查 |
| 8091 | task_manager | 健康检查 |
| 8094 | agent_vectordb | 健康检查 |
| 8100 | monitor | 系统状态 API |
| 8200 | brain_gateway | 外部流量入口 |
| 8765 | health_check | 系统健康汇总 |
| 8766 | task_manager_runtime | 健康检查 |

---

## 5. 关键路径速查

| 用途 | 路径 |
|------|------|
| Agent 注册表 | `/brain/infrastructure/config/agentctl/agents_registry.yaml` |
| 定时器配置 | `/brain/infrastructure/config/timers.yaml` |
| Supervisord 配置 | `/brain/infrastructure/config/supervisord.d/*.conf` |
| 网关路由配置 | `/brain/infrastructure/service/brain_gateway/config/brain_gateway.json` |
| 运行时日志 | `/xkagent_infra/runtime/logs/` |
| 运行时数据 | `/xkagent_infra/runtime/data/` |
| 共享数据库 | `/xkagent_infra/runtime/data/brain_shared.db` |
| Secrets | `/brain/secrets/` |
| Python IPC 客户端 | `/brain/infrastructure/service/utils/ipc/bin/current/ipc_client.py` |

---

## 6. 架构拓扑

```
                        ┌─────────────┐
                        │  Telegram    │
                        │  Bot API     │
                        └──────┬───────┘
                               │ HTTPS polling
                        ┌──────▼───────┐
                        │ telegram_api │
                        │  (Python)    │
                        └──────┬───────┘
                               │ IPC
     ┌─────────────────────────▼─────────────────────────┐
     │              brain_ipc daemon (C)                  │
     │         /tmp/brain_ipc.sock (JSON protocol)        │
     │    ┌─────────────────────────────────────────┐     │
     │    │  Message Queue │ Agent Registry │ Sched  │     │
     │    └─────────────────────────────────────────┘     │
     └──┬──────┬──────┬──────┬──────┬──────┬──────┬───────┘
        │      │      │      │      │      │      │
    ┌───▼──┐┌──▼──┐┌──▼──┐┌──▼──┐┌──▼───┐┌─▼──┐┌─▼────────┐
    │agent ││agent││agent││timer││vector││task││  agentctl │
    │(tmux)││(tmux)││(tmux)││     ││  db  ││mgr ││  service  │
    │      ││     ││     ││     ││      ││    ││           │
    │MCP   ││MCP  ││MCP  ││sock ││sock  ││sock││  sock     │
    │bridge││bridg││bridg││     ││+MCP  ││    ││           │
    └──────┘└─────┘└─────┘└─────┘└──────┘└────┘└───────────┘
       ↕         ↕         ↕
   mcp-brain  mcp-brain  mcp-brain    ← MCP Server（agent session 内）
   _ipc_c     _ipc_c     _ipc_c         通过 stdio JSON-RPC 桥接到 daemon socket
```

### 关键架构约束

1. **Agent（tmux session）** 通过 MCP Server 间接访问 IPC daemon
   - `mcp-brain_ipc_c` 是 C 编译的 MCP server，每个 agent session 启动一个实例
   - MCP server 内部连接 `/tmp/brain_ipc.sock`，转换 JSON-RPC ↔ daemon JSON 协议

2. **独立服务（Python/C）** 直接连接 daemon socket
   - 使用 `DaemonClient` 类（`utils/ipc`）或自行 `socket.connect()`
   - **不能**调用 MCP 工具（MCP 工具仅 agent CLI 可用）

3. **消息推送通知**
   - daemon 发送 tmux 推送（`[IPC] New message...`）给 agent
   - 服务使用 `NotifyClient` 监听 notify socket 获取实时事件


### Design Pitfalls（架构师必读）

> **WARNING: MCP 工具 vs daemon socket**
>
> - MCP 工具（ipc_send, ipc_recv 等）**仅在 agent 会话内可用**（通过 stdio JSON-RPC）
> - 独立 Python/C 服务**不能**调用 MCP 工具，必须直接连接 daemon socket
> - 不存在 `from mcp_ipc import ...` 这样的模块
> - 正确做法：使用 `DaemonClient("/tmp/brain_ipc.sock")`（见 `python_ipc_client.md`）
>
> BS-025 教训：architect 误认为 MCP 工具可在独立服务中调用，导致整个项目 IPC 层无法工作。

### 命名约定

| 上下文 | 命名格式 | 示例 |
|--------|----------|------|
| supervisord program | 无 `service-` 前缀 | `brain_gateway`, `task_manager` |
| IPC daemon 注册名 | `service-` 前缀 | `service-brain_gateway`, `service-task_manager` |
| Agent tmux session | agent 全名 | `agent_system_dev` |

### 服务状态说明

| 状态 | 含义 |
|------|------|
| **running** | 已部署且正在运行 |
| **stopped** | 已部署但未启动（autostart=false） |
| **removed** | 代码/配置已移除 |
| **broken** | 代码存在但无法正常工作 |

---

## 6.5 运维速查

### 常用 supervisorctl 命令

```bash
supervisorctl status                    # 查看所有服务状态
supervisorctl restart <service>         # 重启单个服务
supervisorctl stop <service>            # 停止单个服务
supervisorctl reread && supervisorctl update  # 重载配置并应用
supervisorctl tail -n 50 <service>      # 查看最近日志
```

### 心跳与超时

| 参数 | 值 | 说明 |
|------|-----|------|
| 服务心跳间隔 | 60s（推荐） | 服务应每 60s 调用 service_heartbeat |
| HEARTBEAT_TIMEOUT | 300s | daemon 超过 5 分钟未收到心跳，判定离线 |
| TMUX_DISCOVERY_INTERVAL | 2s | daemon 自动发现 tmux session 间隔 |

## 7. 新服务开发指南

开发独立 Python 服务（如 task_manager_runtime 类型）时：

### 必须做的

1. **连接 IPC daemon socket**（不是 MCP）
   ```python
   from daemon_client import DaemonClient
   client = DaemonClient("/tmp/brain_ipc.sock")
   client.register_service("service-my_service")
   ```

2. **注册 service 身份** — 启动时调用 `service_register`
3. **定期发心跳** — 每 60s 调用 `service_heartbeat`（daemon 300s 超时判定离线）
4. **使用 NotifyClient 监听消息** — 不要轮询 `ipc_recv`
5. **遵循 service 目录结构** — 见 `service_directory_guide.md`

### 禁止做的

1. ~~`from mcp_ipc import ipc_send`~~ — 不存在这个模块
2. ~~`import mcp; mcp.tools.call("ipc_send")`~~ — MCP 工具不能从 Python 调用
3. ~~轮询 `ipc_recv`~~ — 使用 notify socket 事件驱动

### 参考实现

- `timer` 服务 — `infrastructure/service/timer/releases/v1.0.0/src/timer/`
- `supervisor_bridge` — 最简单的 IPC service 参考
- `dashboard` — 完整的异步服务参考
- Python IPC 客户端 — `infrastructure/service/utils/ipc/` (DaemonClient + NotifyClient)

---

## 版本

- 文档版本：1.0
- 创建日期：2026-02-22
- 创建原因：BS-025 post-mortem 发现 base knowledge 缺乏基础设施文档，导致 architect 设计错误（将 MCP 工具误认为可在独立服务中调用）
