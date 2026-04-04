---
id: G-SKILL-ADD-AGENT
name: add-agent
description: "当需要创建新 Agent、刷新已有 Agent 配置、或了解 agent 自动配置内容时使用。"
user-invocable: true
disable-model-invocation: false
allowed-tools: Bash, Read
argument-hint: "[agent_name] [group] [--role ROLE] [--agent-type TYPE] [--model MODEL]"
metadata:
  status: active
  source_project: /xkagent_infra/groups/brain/projects/base
  publish_target: /xkagent_infra/brain/base/skill/add-agent
  spec_ref: /brain/base/spec/policies/agents/agents_registry_spec.yaml
---

# /add-agent — 创建与配置 Agent

```bash
AGENTCTL="python3 /xkagent_infra/brain/infrastructure/service/agentctl/bin/agentctl \
  --config-dir /xkagent_infra/brain/infrastructure/config/agentctl"
```

---

## 触发场景

| 情境 | 跳转 |
|------|------|
| 创建新 agent | → [创建流程](#创建流程) |
| 刷新已有 agent 的配置（skill/mcp 变更后） | → [刷新配置](#刷新配置) |
| 了解 agent 创建后自动生成了什么 | → [自动配置清单](#自动配置清单) |

---

## 创建流程

### Step 1 — Dry-run 预览

```bash
$AGENTCTL add <agent_name> \
  --group <group> \
  --role <role> \
  --agent-type claude \
  --model Sonnet
```

确认输出的 cwd、role、capabilities 无误后继续。

### Step 2 — 执行

```bash
$AGENTCTL add <agent_name> \
  --group <group> \
  --role <role> \
  --agent-type claude \
  --model Sonnet \
  --apply
```

### Step 3 — 验证

```bash
$AGENTCTL list   # 确认新 agent 出现

# 验证 skill 文件已部署
ls <agent_cwd>/.claude/skills/

# 验证 .mcp.json 包含 task_manager
grep mcp-brain_task_manager <agent_cwd>/.mcp.json
```

---

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `name` | agent 名称，如 `agent-brain_dev2` | 必填 |
| `--group` | 所属 group，如 `brain_system` | 必填 |
| `--role` | 角色，见下方角色表 | 从 name 最后一段解析 |
| `--agent-type` | AI 提供商，见对照表 | `claude` |
| `--cli-type` | `claude`\|`native` | 从 agent-type 推断 |
| `--model` | 模型名，见对照表 | 从角色模板获取 |
| `--desired-state` | `stopped`\|`running` | `stopped` |
| `--capabilities` | 逗号分隔能力列表 | 从角色模板获取 |
| `--tags` | 逗号分隔标签列表 | 从角色模板获取 |
| `--apply` | 实际执行（默认 dry-run） | — |

### agent-type × model 对照表

| agent-type | cli-type | 可用 model | 默认 model |
|------------|----------|------------|------------|
| claude | (空) | Sonnet / Opus / Haiku | Sonnet |
| codex | (空) | gpt-5.2-codex | gpt-5.2-codex |
| kimi | (空) | kimi-code | kimi-code |
| minimax | claude | MiniMax-M2.5 | MiniMax-M2.5 |
| gemini | (空) | gemini-2.5-pro | gemini-2.5-pro |
| custom | 手动指定 | 手动指定 | — |

---

## 自动配置清单

`agentctl add --apply` 执行后，以下内容**全部自动生成**，无需手动操作：

### 1. `.mcp.json` — 默认内置 MCP

每个 agent 无论 role 是什么，都会内置以下 MCP：

| MCP | 用途 |
|-----|------|
| `mcp-brain_ipc` | Agent 间 IPC 通信（所有 agent 必需） |
| `mcp-brain_google_api` | Google 搜索 / Sheets / Drive |
| `mcp-brain_task_manager` | 项目与任务管理（所有 agent 必需） |

若 agents_registry.yaml 的 agent 条目中有 `mcp_servers` 字段，会在上述基础上追加。

### 2. `.claude/skills/` — Skill 文件

根据 agent 的 role，从 `skill_bindings.yaml` 解析绑定的 skill 列表，并将 `/brain/base/skill/<name>/` 的文件**逐一复制**到 `.claude/skills/<name>/`。

**各 role 默认 skill 集合：**

| role | skills |
|------|--------|
| manager | preset · brain-publish · lep · agentctl · ipc · sandbox · **task-manager** |
| pmo | lep · ipc · **task-manager** |
| devops | brain-publish · lep · agentctl · tmux · sandbox · **task-manager** |
| dev | lep · doc-search · tmux · sandbox · **task-manager** |
| frontdesk | lep · ipc · **task-manager** |
| custom | lep · **task-manager** |

`task-manager` 是所有 role 的标配。agent 创建后即可直接使用 `/task-manager` skill 和 `mcp-brain_task_manager` 的所有工具。

skill 绑定配置源文件：
```
/brain/infrastructure/config/agentctl/skill_bindings.yaml
```

### 3. `CLAUDE.md` — Agent 系统提示

包含 role 定义、已绑定 skill 列表、工作目录路由规则。

### 4. `.claude/settings.local.json` — Claude CLI 启动配置

注入以下环境变量供 Claude CLI 使用：

| 变量 | 内容 |
|------|------|
| `BRAIN_ENABLED_SKILLS` | 逗号分隔的已绑定 skill 名称 |
| `BRAIN_SKILL_BINDINGS_FILE` | skill_bindings.yaml 路径 |
| `BRAIN_ROLE_DEFAULT_SKILLS` | 该 role 的默认 skills |
| `BRAIN_AGENT_EXTRA_SKILLS` | 该 agent 的额外 skills |

### 5. `agents_registry.yaml` — 注册

写入 `/brain/infrastructure/config/agentctl/agents_registry.yaml`。

---

## 刷新配置

修改了 `skill_bindings.yaml`、`brain/base/skill/` 内容、或 `agents_registry.yaml` 后，对已有 agent 执行：

```bash
# 预览（dry-run）
$AGENTCTL apply-config <agent_name>

# 重新生成：.mcp.json + 部署最新 skill 文件 + settings.local.json
$AGENTCTL apply-config <agent_name> --apply

# 同时强制覆盖 CLAUDE.md
$AGENTCTL apply-config <agent_name> --apply --force

# 批量刷新所有 agent
$AGENTCTL apply-config --all --apply
```

---

## 示例

```bash
# 创建 brain 团队的 dev agent
$AGENTCTL add agent-brain_dev2 \
  --group brain_system --role dev --model Opus --apply

# 验证结果
ls /xkagent_infra/groups/brain_system/agents/agent-brain_dev2/.claude/skills/
# → doc-search  lep  sandbox  task-manager  tmux

grep -l "mcp-brain_task_manager" \
  /xkagent_infra/groups/brain_system/agents/agent-brain_dev2/.mcp.json
```
