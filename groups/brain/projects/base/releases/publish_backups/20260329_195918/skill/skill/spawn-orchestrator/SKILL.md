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
- registry 只能写到 sandbox-local bridge：`/xkagent_infra/runtime/sandbox/<instance_id>/config/agentctl/agents_registry.yaml`。
- proxy client 映射只能写到 sandbox-local overlay：`/xkagent_infra/runtime/sandbox/<instance_id>/config/agentctl/proxy.yaml`。
- 禁止回退到宿主全局 `/xkagent_infra/brain/infrastructure/config/agentctl/agents_registry.yaml`。
- 禁止写宿主全局 `/xkagent_infra/brain/infrastructure/service/brain_agent_proxy/config/proxy.yaml`。
- 如果 sandbox bridge 不存在，必须记录 blocker，不能先在 `/xkagent_infra/brain/agents` 创建一个“临时 orchestrator”顶着用。
- agentctl 失败时禁止回退到直接 `tmux new-session` / `tmux send-keys`；必须记录 blocker 并通过 workflow 上报。

## Bootstrap Gate

创建前先验证：

```bash
test -f /xkagent_infra/runtime/sandbox/<instance_id>/config/agentctl/agents_registry.yaml
test -d /xkagent_infra/runtime/sandbox/<instance_id>/agents
```

任一不存在：
- 停止 spawn
- 记录 `sandbox bootstrap / registry bridge missing`
- 通知 manager/PMO 当前 workflow 仍卡在 bootstrap

## Create

```bash
SANDBOX_SERVICE="/xkagent_infra/brain/bin/sandboxctl"

$SANDBOX_SERVICE create BS-029 \
  --type development \
  --with-agent orchestrator \
  --pending-id BS-029
```

成功后验证：

```bash
test -f /xkagent_infra/runtime/sandbox/156yk8/config/agentctl/agents_registry.yaml
test -f /xkagent_infra/runtime/sandbox/156yk8/agents/agent_brain_BS-029_orchestrator_01/.brain/agent_runtime.json
docker exec brain-BS-029-development-156yk8 tmux has-session -t agent_brain_BS-029_orchestrator_01
```

## Spawn Project Agents

在 sandbox 内为 designer / dev / qa / worker 添加 project-scoped agent 时，必须使用 sandbox service bundle 黑盒接口：

```bash
/xkagent_infra/runtime/sandbox/_services/service/brain_sandbox_service/bin/brain_sandbox_service \
  spawn-agent <project_id> \
  --instance <instance_id> \
  --role <designer|dev|qa|worker> \
  [--slot <NN>] \
  [--model <provider/model>]
```

规则：
- 命名、tmux_session、sandbox-local registry 与 proxy overlay 由 sandbox service 统一生成
- runtime root 必须落在 `/xkagent_infra/runtime/sandbox/<instance_id>/agents/...`
- 如果 spawn 失败，不要直接 tmux 启动，必须把 blocker 回给 manager / PMO

## Handoff

PMO / manager 启动 project orchestrator 后，必须通过 IPC 注入项目上下文：

```python
ipc_send(
    to="agent_brain_BS-029_orchestrator_01",
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
