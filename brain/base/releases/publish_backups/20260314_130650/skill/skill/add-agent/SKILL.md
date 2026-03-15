---
id: G-SKILL-ADD-AGENT
name: add-agent
description: "交互式添加新 Agent 到 agents_registry"
allowed-tools: ["Bash", "AskUserQuestion", "Read"]
---

# Add Agent Command

通过 `agentctl add` 添加新 Agent。本命令只负责收集参数，实际操作全部由 agentctl 执行。

## 参数解析

命令格式: `/add-agent [agent_name] [group]`

如果参数已提供，跳过对应的交互步骤。

## agentctl add 完整参数

```
agentctl add <name> --group <group> [options] --apply

Options:
  --role            角色 (默认: 从 name 自动解析)
  --agent-type      AI 提供商 (默认: claude)
  --cli-type        CLI 类型 (默认: 从 agent_type 推断)
  --model           模型名 (默认: 从角色模板获取)
  --desired-state   stopped|running (默认: stopped)
  --capabilities    逗号分隔的能力列表
  --tags            逗号分隔的标签列表
```

## agent_type 与 model 对照表

交互时**必须**按此表展示选项：

| agent_type | cli_type | 可用 model | 默认 model | 说明 |
|------------|----------|------------|------------|------|
| claude | (空) | Sonnet, Opus, Haiku | Sonnet | Claude Code CLI 原生 |
| codex | (空) | gpt-5.2-codex | gpt-5.2-codex | OpenAI Codex CLI |
| kimi | (空) | kimi-code/kimi-for-coding | kimi-code/kimi-for-coding | Kimi CLI (native) |
| minimax | claude | MiniMax-M2.5 | MiniMax-M2.5 | 通过 Claude Code CLI 代理启动 |
| gemini | (空) | gemini-2.5-pro | gemini-2.5-pro | Google Gemini CLI |
| custom | 手动指定 | 手动指定 | (无) | 自定义 |

## 工作流程

### Step 1: 确定 Group

如果参数未提供 group，用 AskUserQuestion 选择已有 group。

### Step 2: 确定 Agent 名称

如果参数未提供 name，根据 group 和角色生成: `agent_{group_alias}_{role}`

### Step 3: 选择 agent_type

用 AskUserQuestion 询问，选项包括全部 6 种：
- claude (推荐) — Claude Code CLI
- codex — OpenAI Codex CLI
- kimi — Kimi CLI
- minimax — 通过 Claude Code CLI 代理
- gemini — Google Gemini CLI
- custom — 自定义

### Step 4: 选择 model

根据 Step 3 选择的 agent_type，展示对应的模型选项（参照对照表）。
如果该 agent_type 只有一个模型，跳过此步直接使用默认值。

### Step 5: Dry-run 确认

执行不带 `--apply` 的 dry-run，展示给用户确认：
```bash
/brain/infrastructure/service/agent-ctl/bin/agentctl add <name> --group <group> [options]
```

### Step 6: 执行

用户确认后加 `--apply` 执行：
```bash
/brain/infrastructure/service/agent-ctl/bin/agentctl add <name> --group <group> [options] --apply
```

agentctl 会自动完成：
1. 创建 agent 目录
2. 写入所有 registry (主 + agentctl，共 2 份)
3. 生成 CLAUDE.md + .mcp.json (或 .kimi/config.toml 等)

### Step 7: 验证

执行 `agentctl list` 确认新 agent 已出现。
