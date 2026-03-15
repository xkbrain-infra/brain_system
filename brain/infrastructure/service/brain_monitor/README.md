# Brain 监控系统

基础监控工具集，用于监控 Brain 系统的运行状态。

## Monitor Service API (BS-005) ⭐ 推荐

**统一系统状态查询接口** - 提供一站式系统健康监控。

### 启动服务
```bash
# 使用 releases/current/bin/ 入口点
/brain/infrastructure/service/monitor/releases/current/bin/monitor_service

# 或使用 venv 中的 Python
cd /brain/infrastructure/service/monitor
./venv/bin/python src/monitor_service.py  # 默认端口 8100

**端口规范**（BS-007）:
- **生产端口**: 8100（符合 Brain 端口分配规范：Base 7000 + Offset 100）
- **开发端口**: 9100
- **Stage端口**: 11100
- **测试端口**: 13100

### API 端点

#### GET /api/system/status
**统一系统状态查询**（一次调用获取所有服务状态）

```bash
curl http://127.0.0.1:8100/api/system/status
```

**响应示例**:
```json
{
  "system_status": "healthy",
  "timestamp": "2026-02-09T14:37:40.465064",
  "response_time_ms": 56.17,
  "services": {
    "daemon": {
      "status": "healthy",
      "running": true
    },
    "agents": {
      "status": "healthy",
      "online": 15,
      "total": 16,
      "online_ratio": 0.94
    },
    "ipc": {
      "status": "healthy",
      "total_messages": 100,
      "pending": 5,
      "acked": 95,
      "failed": 0,
      "success_rate": 1.0
    },
    "orchestrator": {
      "status": "healthy",
      "online": true,
      "source": "agent_list"
    },
    "timer": {
      "status": "healthy",
      "running": true,
      "jobs_loaded": 5
    },
    "gateway": {
      "status": "healthy",
      "running": true,
      "adapters": ["telegram"]
    }
  }
}
```

**状态说明**:
- `system_status`: 系统整体状态
  - `healthy`: 所有服务正常
  - `degraded`: 部分服务降级或有非关键服务故障
  - `critical`: 关键服务（如 daemon）故障

- 各服务 `status`:
  - `healthy`: 服务正常运行
  - `degraded`: 服务运行但性能下降
  - `down`: 服务不可用
  - `unknown`: 无法获取服务状态

**服务状态判定规则**:
- **daemon**: `running=true` → healthy
- **agents**: `online_ratio >= 0.95` → healthy, `0.70-0.95` → degraded, `< 0.70` → down
- **ipc**: `failed=0 且 pending <= 100` → healthy
- **orchestrator**: service-agent-orchestrator 在线 → healthy
- **timer**: `/health` status=ok → healthy
- **gateway**: `/health` status=ok → healthy

#### GET /api/health
简单健康检查（仅检查 daemon 连接）

```bash
curl http://127.0.0.1:8100/api/health
```

#### GET /api/agents
列出所有 agents 及其状态

```bash
# 仅在线 agents
curl http://127.0.0.1:8100/api/agents

# 包括离线 agents
curl http://127.0.0.1:8100/api/agents?include_offline=true
```

#### GET /api/agents/stats
Agent 统计摘要

```bash
curl http://127.0.0.1:8100/api/agents/stats
```

#### GET /api/ipc/stats
IPC 消息队列统计

```bash
curl http://127.0.0.1:8100/api/ipc/stats
```

### 性能指标
- **响应时间**: p99 < 60ms @ 10 QPS
- **并发探测**: 6 个服务并发检测
- **超时保护**: 150ms/服务，总体响应 < 500ms

### 故障排查指南

#### System Status = critical
1. 检查 daemon 服务: `ps aux | grep brain_ipc`
2. 检查 daemon socket: `ls -la /tmp/brain_ipc.sock`
3. 重启 IPC 服务: `supervisorctl restart brain_ipc`

#### Agents = down (online_ratio < 0.70)
1. 列出所有 agents: `curl http://127.0.0.1:8100/api/agents?include_offline=true`
2. 检查离线 agents 的 tmux session
3. 检查 orchestrator 日志: `/xkagent_infra/runtime/logs/orchestrator/`

#### IPC = degraded (有失败消息)
1. 查看失败详情: `curl http://127.0.0.1:8100/api/ipc/stats`
2. 检查 IPC state DB: `/xkagent_infra/runtime/data/ipc_state.db`
3. 查看 timer service 日志: `/xkagent_infra/runtime/logs/timer/`

#### Timer/Gateway = down
1. 检查服务进程: `ps aux | grep timer` / `ps aux | grep gateway`
2. 检查日志: `/xkagent_infra/runtime/logs/{service}/`
3. 尝试手动访问 health 端点: `curl http://127.0.0.1:{port}/health`

---

## 命令行工具

### 1. agents_status.py
监控所有注册的 Agent 在线状态和心跳。

**使用方法**:
```bash
# 使用入口点（推荐）
/brain/infrastructure/service/monitor/releases/current/bin/agents_status

# 或直接运行源码
python3 /brain/infrastructure/service/monitor/releases/current/src/agents_status.py
```

**输出**:
- Agent 在线/离线状态
- 最后心跳时间
- Agent 元数据

### 2. ipc_stats.py
统计 IPC 消息的发送、接收和失败情况。

**使用方法**:
```bash
# 使用入口点（推荐）
/brain/infrastructure/service/monitor/releases/current/bin/ipc_stats

# 查看最近 1 小时统计
/brain/infrastructure/service/monitor/releases/current/bin/ipc_stats --hours 1

# 或直接运行源码
python3 /brain/infrastructure/service/monitor/releases/current/src/ipc_stats.py
```

**输出**:
- 总消息数、成功率、失败率
- 按消息类型统计
- 按优先级统计
- Top 10 活跃 Agents

### 3. task_monitor.py
监控 Timer 服务的定时任务执行状态。

**使用方法**:
```bash
# 使用入口点（推荐）
/brain/infrastructure/service/monitor/releases/current/bin/task_monitor

# 查看最近 12 小时任务执行
/brain/infrastructure/service/monitor/releases/current/bin/task_monitor --hours 12

# 或直接运行源码
python3 /brain/infrastructure/service/monitor/releases/current/src/task_monitor.py
```

**输出**:
- 任务执行次数
- 成功率统计
- 最近的失败记录

## 一键查看所有监控

```bash
# 使用入口点
/brain/infrastructure/service/monitor/releases/current/bin/monitor_all
```

## 依赖

- Python 3.8+
- Brain IPC daemon (用于 agents_status.py)
- IPC 日志目录: `/xkagent_infra/runtime/logs/ipc/`
- Timer 日志目录: `/xkagent_infra/runtime/logs/timer/`

## 未来扩展

计划添加的功能：
- Web Dashboard (Flask/FastAPI)
- 实时监控 (WebSocket)
- 告警系统 (Email/Telegram)
- Prometheus metrics 导出
- Grafana 仪表盘集成

---

**创建时间**: 2026-02-09
**创建者**: agent_xkquant_devops
**任务**: XQ-TASK-003
