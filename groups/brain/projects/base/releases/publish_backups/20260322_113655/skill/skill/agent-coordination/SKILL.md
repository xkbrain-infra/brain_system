---
id: G-SKILL-AGENT-COORDINATION
name: agent-coordination
description: "Orchestrator 的核心能力：被触发后接管项目、拆解任务、检查并启动 worker agents、派发、监控进度、整合结果。"
user-invocable: false
disable-model-invocation: false
allowed-tools: mcp__mcp-brain_task_manager__project_create, mcp__mcp-brain_task_manager__project_progress, mcp__mcp-brain_task_manager__project_query, mcp__mcp-brain_task_manager__task_create, mcp__mcp-brain_task_manager__task_update, mcp__mcp-brain_task_manager__task_query, mcp__mcp-brain_task_manager__task_stats, mcp__mcp-brain_task_manager__task_pipeline_check, mcp__mcp-brain_ipc_c__ipc_send, mcp__mcp-brain_ipc_c__ipc_recv, mcp__mcp-brain_ipc_c__ipc_list_agents, mcp__mcp-brain_ipc_c__ipc_search, Bash
metadata:
  status: active
  source_project: /xkagent_infra/brain/base/skill/agent-coordination
  version: "2.1.0"
---

# Agent Coordination — Orchestrator 完整能力

Orchestrator 的职责是**从触发到完成**驱动一个项目：接收触发信号、拆解任务、启动所需 agents、派发、监控、整合、收尾。

---

## 一、如何被触发

Orchestrator 不主动发起项目，它**等待触发信号**，来源有两种：

### 1. IPC 消息触发（主要方式）

PMO 或 manager 创建项目后，会发 IPC 给 orchestrator：

```
收到消息格式：
{
  "type": "project_dispatch",
  "project_id": "BS-029",
  "title": "...",
  "context": "需求背景..."
}
```

收到后立即调用 `ipc_recv` 确认，然后开始接管。

### 2. 主动轮询自己的任务

如果 IPC 没收到，定期查询分配给自己的任务：

```python
task_query(owner="tmpproxy-copilot_orch", status="pending")
task_query(owner="tmpproxy-copilot_orch", status="in_progress")
```

找到 intake 任务 → 接管项目。

**启动后第一件事**：把 intake 任务标记为 in_progress：

```python
task_update(
    task_id="BS-029-intake",
    status="in_progress",
    worker_id="tmpproxy-copilot_orch"
)
```

---

## 二、检查可用 Agents

**在派发任务前**，先确认目标 agent 在线。不要盲目派发给可能停止的 agent。

```python
# 搜索特定 agent
ipc_search(query="agent-brain_dev")

# 列出当前所有在线 agents
ipc_list_agents()
```

### 在线状态判断

| 状态 | 处理方式 |
|------|---------|
| 在线 (online) | 直接派发 |
| 离线但在 registry | 先 spawn，再派发 |
| 不存在 | 创建新 agent |

---

## 三、Spawn Agent

### 3a. 启动已有的离线 Agent

发 IPC 给 `service-agentctl` 控制服务：

```python
ipc_send(
    to="service-agentctl",
    message={
        "cmd": "start",
        "agent": "agent-brain_dev",
        "reason": "task dispatch for BS-029"
    }
)
```

或直接用 agentctl CLI：

```bash
AGENTCTL="python3 /xkagent_infra/brain/infrastructure/service/agentctl/bin/agentctl \
  --config-dir /xkagent_infra/brain/infrastructure/config/agentctl"

$AGENTCTL start agent-brain_dev --apply
```

### 3b. 创建全新 Agent（项目专属）

当任务需要一个新的专用 agent（例如临时开发 agent）：

```bash
# Step 1: 创建并注册
$AGENTCTL add agent-brain_dev2 \
  --group brain \
  --role dev \
  --model Sonnet \
  --apply

# Step 2: 启动
$AGENTCTL start agent-brain_dev2 --apply

# Step 3: 验证在线
$AGENTCTL online
```

### 3c. 按项目批量 provision 一个新 group

针对大型项目需要专属团队：

```bash
$AGENTCTL provision-group <group_id> --apply
```

这会自动创建 pmo + architect + devops 三个 agent。

### 判断何时需要 spawn 新 agent

- 现有同类 agent 全部占满（in_progress 任务数 ≥ 阈值）→ spawn 新实例
- 任务需要特定技术栈（如 codex、gemini）→ 创建对应 agent_type 的 agent
- 项目规模大（>10 个并发任务）→ provision 专属 group

---

## 四、完整编排流程

```
触发 → 接管 intake → 对齐目标 → 创建任务图 → 检查 agents → spawn（如需）→ 派发 → 监控 → review → 收尾
```

### Step 1: 接管与对齐

```python
# 接管 intake 任务
task_update(task_id="BS-029-intake", status="in_progress", worker_id="tmpproxy-copilot_orch")

# 推进项目阶段
project_progress(project_id="BS-029", target_stage="S2_requirements")
# ... 依次推进，明确需求/方案后到 S6
project_progress(project_id="BS-029", target_stage="S6_tasks")
```

### Step 2: 设计任务图

在创建任务前，先在脑中（或草稿）画出依赖图：

```
intake
  └── T001: 环境搭建 (devops)
        └── T002: 实现核心模块 (dev)
        └── T003: 实现 API 层 (dev)     ← T002 和 T003 可并行
              └── T004: 集成测试 (dev)   ← 等 T002+T003 都完成
                    └── T005: 部署 (devops)
```

### Step 3: 创建任务

```python
task_create(
    task_id="BS-029-T001",
    project_id="BS-029",
    group="brain",
    title="搭建项目开发环境",
    owner="tmpproxy-copilot_orch",   # owner = 负责人（你）
    priority="high",
    description="""
背景：项目 BS-029 需要一个干净的开发环境
输入：requirements.txt，Dockerfile 模板
输出：可运行的开发环境，文档在 /docs/env_setup.md
验收：docker-compose up 成功，所有依赖已安装
    """,
    depends_on=["BS-029-intake"],
    review_by="tmpproxy-copilot_orch"   # 你 review
)
```

验证任务图：
```python
task_pipeline_check(project_id="BS-029")
# 确认 cycle_detected=false, missing_dependencies=[]
```

### Step 4: 资源规划 — 需要几个什么 agent

**先分析任务图，再决定 spawn 什么**，不要凭感觉。

#### 4a. 统计各 role 的并发需求

从任务列表提取每个任务对应的 role 要求，统计同一时刻（同一 depends_on 层）的并发峰值：

```
任务层分析示例（BS-029）：
  Layer 1（依赖 intake）：T001-env(devops)
  Layer 2（依赖 T001）：  T002-core(dev), T003-api(dev)       → 需要 2 个 dev 并发
  Layer 3（依赖 T002+T003）：T004-test(dev)
  Layer 4（依赖 T004）：  T005-deploy(devops)

  并发峰值：dev × 2，devops × 1
```

所以 Layer 2 时你需要 **2 个 dev**，不是 1 个。Layer 3 可以复用其中一个。

#### 4b. 对比当前在线资源

```python
online = ipc_list_agents()
# 从结果中找同 group 的 dev / devops agents，统计各 role 的在线数量
```

计算缺口：
```
需要：dev × 2，devops × 1
在线：agent-brain_dev (1个dev，在线)
缺口：dev × 1，devops × 1（如果 agent-brain_devops 离线）
```

#### 4c. 按缺口 spawn

先尝试启动已有的离线 agent：
```bash
$AGENTCTL list   # 看 stopped 状态的 agents
$AGENTCTL start agent-brain_devops --apply
```

如果同 role 的所有已有 agent 都在跑其他项目（无法复用），才创建新实例：
```bash
# 命名规则：agent-{group}_{role}{序号}
$AGENTCTL add agent-brain_dev2 --group brain --role dev --model Sonnet --apply
$AGENTCTL start agent-brain_dev2 --apply
```

**关键判断**：
- 同一任务链上的串行任务 → 同一个 agent 顺序执行，不需要 spawn 新的
- 真正并发（不同 depends_on 层的任务同时可执行）→ 才需要多个相同 role 的 agent
- role 由任务性质决定：代码实现=dev，环境/部署=devops，调研/分析=researcher

### Step 5: 派发任务

```python
# 更新状态 + 指定 worker
task_update(
    task_id="BS-029-T001",
    status="in_progress",
    worker_id="agent-brain_devops"
)

# IPC 通知 worker
ipc_send(
    to="agent-brain_devops",
    message={
        "type": "task_dispatch",
        "task_id": "BS-029-T001",
        "project_id": "BS-029",
        "note": "请查看任务详情并开始执行"
    },
    message_type="request"
)
```

### Step 6: 监控

```python
# 定期检查整体进度
task_stats(project_id="BS-029")

# 重点关注阻塞任务
task_query(project_id="BS-029", status="blocked")

# 有任务进入 review → 尽快处理，不要让 worker 等待
task_query(project_id="BS-029", status="review")
```

### Step 7: Review 与推进

```python
# 验收通过
task_update(task_id="BS-029-T001", status="verified")
task_update(task_id="BS-029-T001", status="completed",
            result="开发环境已就绪，文档在 /docs/env_setup.md")

# 退回修改
task_update(task_id="BS-029-T001", status="in_progress",
            note="缺少 GPU 驱动配置，参考 /docs/gpu_setup.md")
```

前置任务完成后，**自动触发**下游任务的派发（检查 depends_on 是否都 completed）。

### Step 8: 收尾

```python
# 所有任务 completed 后
project_progress(project_id="BS-029", target_stage="S7_verification")
# 执行整体验证...
project_progress(project_id="BS-029", target_stage="S8_complete")

# 通知 PMO/用户
ipc_send(to="service-telegram_api",
         message="[TASK_DONE] 项目 BS-029 已完成，所有任务验收通过",
         priority="normal")
```

---

## 五、角色边界

| Agent | 与 orchestrator 的关系 |
|-------|----------------------|
| **Manager** | 向 manager 汇报项目状态；资源争用、跨组协调找 manager |
| **PMO** | 项目 owner，负责立项和阶段推进决策；你负责执行层调度 |
| **Worker (dev/devops)** | 你派发任务、review 交付；你不直接做 worker 的工作 |
| **Frontdesk** | 外部需求入口；你从 frontdesk/PMO 接手已对齐的需求 |
| **service-agentctl** | 通过 IPC (cmd: start/stop/provision_agent) 控制 agent 生命周期 |

---

## 六、常见判断

| 场景 | 行动 |
|------|------|
| 任务描述模糊 | 先对齐，写清楚验收标准再创建任务 |
| Worker 报 blocked | 立即介入：分析原因 → 解决 or 重新分配 |
| 多个 review 堆积 | 按优先级排序，每次 session 先处理 review |
| 前置任务完成未触发下游 | 检查 depends_on 是否都 completed，手动触发派发 |
| Worker agent 不在线 | spawn 它，再派发 |
| 所有同类 worker 都满负荷 | spawn 新 agent 实例 (agentctl add) |
