---
id: G-SKILL-AGENTCTL
name: agentctl
description: "当需要启动、停止、重启、查看 agent 状态、或刷新 agent 配置时使用。禁止直接 tmux 操作 agent session。"
user-invocable: true
disable-model-invocation: false
allowed-tools: Bash, Read
argument-hint: "[list|online|start|stop|restart|apply-config|purge] [agent_name...]"
metadata:
  status: active
  source_project: /xkagent_infra/groups/brain/projects/base
  publish_target: /xkagent_infra/brain/base/skill/agentctl
  spec_ref: /brain/base/spec/policies/agents/agents_registry_spec.yaml
---

# agentctl

<!-- L1 -->
## 触发场景

| 情境 | 跳转 |
|------|------|
| 查看 agent 列表 / 状态 | → [查询](#查询) |
| 启动 / 停止 / 重启 agent | → [生命周期操作](#生命周期操作) |
| 配置变更后让 agent 生效 | → [刷新配置](#刷新配置) |
| 删除或彻底清除 agent | → [删除操作](#删除操作) |
| 添加新 agent | → 使用 `/add-agent` |

**约束：** 默认 dry-run，加 `--apply` 才真正执行。

---

```bash
AGENTCTL="python3 /xkagent_infra/brain/infrastructure/service/agentctl/bin/agentctl \
  --config-dir /xkagent_infra/brain/infrastructure/config/agentctl"
```

<!-- L3 -->
## 查询

```bash
$AGENTCTL list             # 所有 agent 及 tmux 状态
$AGENTCTL online           # 当前在线的 agent（IPC 可达）
```

---

## 生命周期操作

```bash
# dry-run 预览（默认）
$AGENTCTL start|stop|restart <name> [<name2> ...]

# 实际执行
$AGENTCTL start|stop|restart <name> --apply

# 验证
$AGENTCTL list
```

---

## 刷新配置

修改 `agents_registry.yaml` / `skill_bindings.yaml` / `lep_bindings.yaml` 后：

```bash
# 生成新配置（dry-run）
$AGENTCTL apply-config <name>

# 写入并重启生效
$AGENTCTL apply-config <name> --apply
$AGENTCTL restart <name> --apply

# 验证上线
$AGENTCTL online
```

> skill 变更的配置刷新请用 `/brain-publish`，不是此 skill 的职责。

---

## 删除操作

```bash
# 仅从 registry 删除（保留目录）
$AGENTCTL delete <name> --apply

# 完全清除（stop + delete + 目录）
$AGENTCTL purge <name> --apply --force
```

---

## Spec 引用

| 场景 | 读取路径 | 读取时机 |
|------|----------|----------|
| agent 注册结构规范 | `spec_ref` | 需要理解字段语义时 |
| skill 绑定配置 | `/brain/infrastructure/config/agentctl/skill_bindings.yaml` | 排查 skill 未生效时 |

`spec_ref` = `/brain/base/spec/policies/agents/agents_registry_spec.yaml`
