---
id: G-SKILL-AGENTCTL
name: agentctl
description: "This skill should be used when the user asks to \"启动 agent\", \"停止 agent\", \"重启 agent\", \"删除 agent\", \"查看 agent 列表\", \"agent 状态\", or mentions agent lifecycle operations (start/stop/restart/purge/list)."
user-invocable: true
disable-model-invocation: false
allowed-tools: Bash, Read
argument-hint: "[start|stop|restart|purge|delete|list] [agent_name...]"
---

# agentctl — Agent 生命周期管理

**路径**: `/brain/infrastructure/service/agent-ctl/bin/agentctl`

禁止直接 tmux 操作 agent session，必须通过 agentctl。默认 dry-run，加 `--apply` 才执行。

## 参数解析

`/agentctl $ARGUMENTS`:
- 空或 `list` → `agentctl list`
- `online` → `agentctl online`
- `start|stop|restart <name>` → 对应操作（加 `--apply`）
- `delete|purge <name>` → 加 `--apply --force`
- 支持多 name 空格分隔: `stop agent1 agent2`
- 添加 agent → 使用 `/add-agent`

## 执行流程

1. 先不带 `--apply` 执行 dry-run 预览
2. 加 `--apply` 实际执行
3. 执行 `agentctl list` 验证结果
