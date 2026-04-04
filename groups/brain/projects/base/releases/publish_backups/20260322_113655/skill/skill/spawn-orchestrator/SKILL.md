---
id: G-SKILL-SPAWN-ORCHESTRATOR
name: spawn-orchestrator
description: "为项目创建专属 agent（orchestrator、worker 或子 orchestrator）并完成移交。PMO/Manager 用来 spawn orchestrator；orchestrator 用来 spawn worker agents。"
user-invocable: true
disable-model-invocation: false
allowed-tools: Bash, mcp__mcp-brain_task_manager__task_update, mcp__mcp-brain_task_manager__task_query, mcp__mcp-brain_ipc_c__ipc_send, mcp__mcp-brain_ipc_c__ipc_list_agents
argument-hint: "<project_id> <group> <role> [--model Opus|Sonnet|Haiku] [--count N]"
metadata:
  status: active
  source_project: /xkagent_infra/brain/base/skill/spawn-orchestrator
  version: "1.1.0"
---

# spawn-orchestrator — 为项目 Spawn Agent

**谁用、用来干什么：**

| 调用者 | Spawn 的对象 | 时机 |
|--------|-------------|------|
| PMO / Manager | orchestrator | 项目立项，任务规划完成后 |
| Orchestrator | worker（dev / devops / researcher 等） | 任务图分析后，按并发需求 spawn |
| Orchestrator | 子 orchestrator | 子项目规模足够大，需要独立编排 |

---

## 核心流程（适用所有 role）

### Step 1: 确定需要 spawn 什么

**PMO/Manager 的判断**：
- 项目 ≥ 5 个任务，或需要并发执行 → spawn orchestrator
- 小项目串行执行 → PMO 直接派发，不 spawn

**Orchestrator 的判断**（每次任务派发前）：
1. 分析任务图，按 depends_on 分层，找并发峰值
2. `ipc_list_agents()` 查当前在线 agents
3. 计算各 role 的缺口（需要数 - 在线数 = 要 spawn 的数量）
4. 缺口 > 0 才 spawn，不要无谓创建

```
示例（BS-029 Layer 2 需要 2 个 dev，当前在线 1 个）：
  缺口 = dev×1 → spawn 1 个新 dev agent
```

### Step 2: 命名

```
格式：agent-{group}_{role}{序号}
                           ↑ 同 group 同 role 已有几个，就从下一个序号开始

例：
  group=brain, role=orchestrator → agent-brain_orch（第一个）
  group=brain, role=dev, 已有 agent-brain_dev → agent-brain_dev2
  group=brain, role=devops       → agent-brain_devops（如不存在）
```

已有 agent 只是 stopped → **先 start，不要重复创建**：
```bash
$AGENTCTL list | grep brain_dev   # 看有没有 stopped 的
$AGENTCTL start agent-brain_dev --apply
```

### Step 3: 创建 + 启动

```bash
AGENTCTL="python3 /xkagent_infra/brain/infrastructure/service/agentctl/bin/agentctl \
  --config-dir /xkagent_infra/brain/infrastructure/config/agentctl"

# dry-run
$AGENTCTL add agent-brain_dev2 \
  --group brain \
  --role dev \
  --model Sonnet

# 确认无误
$AGENTCTL add agent-brain_dev2 --group brain --role dev --model Sonnet --apply

# 启动
$AGENTCTL start agent-brain_dev2 --apply

# 等待上线（轮询，最多 60s）
$AGENTCTL online | grep dev2
```

### Step 4: 注入上下文并移交

**Orchestrator spawn worker 时**，必须通过 IPC 告诉 worker 它的任务：

```python
ipc_send(
    to="agent-brain_dev2",
    message={
        "type": "task_dispatch",
        "task_id": "BS-029-T002",
        "project_id": "BS-029",
        "title": "实现核心数据采集模块",
        "description": "详见 task_query(task_id=BS-029-T002)",
        "inputs": ["BS-029-T001 的产出：/docs/env_setup.md"],
        "expected_output": "/src/collector.py + 单元测试",
        "acceptance": "pytest 全部通过，覆盖率 ≥ 80%",
        "report_to": "agent-brain_orch_bs029",   # 完成后汇报给我
        "deadline": "2026-03-25T00:00:00Z"
    },
    message_type="request",
    priority="high"
)
```

**PMO spawn orchestrator 时**，注入项目上下文：

```python
ipc_send(
    to="agent-brain_orch_bs029",
    message={
        "type": "project_dispatch",
        "project_id": "BS-029",
        "group": "brain",
        "title": "项目标题",
        "intake_task_id": "BS-029-intake",
        "owner_pmo": "agent-brain_pmo",
        "context": "需求背景和关键约束..."
    },
    message_type="request",
    priority="high"
)
```

### Step 5: 在 task_manager 记录

```python
task_update(
    task_id="BS-029-T002",
    status="in_progress",
    worker_id="agent-brain_dev2"
)
```

---

## 项目结束后清理

```bash
# 停止（保留 registry，可复用）
$AGENTCTL stop agent-brain_dev2 --apply

# 彻底清除（不再需要）
$AGENTCTL purge agent-brain_dev2 --apply --force
```

Orchestrator 在项目进入 S8_complete 后负责 stop 所有它 spawn 的 worker agents。
