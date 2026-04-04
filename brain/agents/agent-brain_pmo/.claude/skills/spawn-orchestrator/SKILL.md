---
id: G-SKILL-SPAWN-ORCHESTRATOR
name: spawn-orchestrator
description: "为项目创建专属 agent（orchestrator、worker 或子 orchestrator）并完成移交。PMO/Manager 用来 spawn orchestrator；orchestrator 用来 spawn worker agents。"
user-invocable: true
disable-model-invocation: false
allowed-tools: Bash, mcp__mcp-brain_task_manager__task_update, mcp__mcp-brain_task_manager__task_query, mcp__mcp-brain_ipc_c__ipc_send, mcp__mcp-brain_ipc_c__ipc_list_agents
argument-hint: "<project_id> <group> <role> [--model <provider/model>] [--count N]"
metadata:
  status: active
  source_project: /xkagent_infra/brain/base/skill/spawn-orchestrator
  version: "1.2.0"
---

# spawn-orchestrator

## Hard Rules

- project-scoped orchestrator / worker 只能创建在 sandbox 内的 runtime home。
- registry 只能写到 sandbox-local bridge：`/workspace/runtime/config/agentctl/agents_registry.yaml`。
- 禁止回退到宿主全局 `/xkagent_infra/brain/infrastructure/config/agentctl/agents_registry.yaml`。
- 如果 sandbox bridge 不存在，必须记录 blocker，不能先在 `/xkagent_infra/brain/agents` 创建一个“临时 orchestrator”顶着用。

## Bootstrap Gate

创建前先验证：

```bash
test -f /workspace/runtime/config/agentctl/agents_registry.yaml
test -d /workspace/runtime/agents
```

任一不存在：
- 停止 spawn
- 记录 `sandbox bootstrap / registry bridge missing`
- 通知 manager/PMO 当前 workflow 仍卡在 bootstrap

## Create

```bash
AGENTCTL="python3 /xkagent_infra/brain/infrastructure/service/agentctl/bin/agentctl \
  --config-dir /workspace/runtime/config/agentctl"

$AGENTCTL add agent-brain_orch_bs029 \
  --group brain \
  --role orchestrator \
  --scope project \
  --project BS-029 \
  --sandbox-id 156yk8 \
  --runtime-root /workspace/runtime \
  --model claude-opus-4.6 \
  --apply

$AGENTCTL start agent-brain_orch_bs029 --apply
$AGENTCTL list | grep agent-brain_orch_bs029
```

## Handoff

PMO / manager 启动 project orchestrator 后，必须通过 IPC 注入项目上下文：

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
