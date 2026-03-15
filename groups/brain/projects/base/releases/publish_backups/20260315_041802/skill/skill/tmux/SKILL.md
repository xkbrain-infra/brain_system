---
id: G-SKILL-TMUX
name: tmux
description: "This skill should be used when the user asks to \"看看 agent 在干什么\", \"捕获 pane\", \"查看 agent 内容\", \"看看终端\", \"agent 屏幕\", \"tmux capture\", or wants to view agent terminal output."
user-invocable: true
disable-model-invocation: false
allowed-tools: Bash, Read
argument-hint: "[capture|ls|panes] [agent_name] [-n lines]"
---

# tmux — Agent 终端查看（只读）

**路径**: `/brain/infrastructure/service/utils/tmux/bin/brain_tmux_api`

禁止直接 tmux 命令，必须通过 brain_tmux_api。仅只读查看，生命周期管理使用 `/agentctl`。

## 参数解析

`/tmux $ARGUMENTS`:
- 空或 `ls` → `brain_tmux_api list-sessions`
- `<agent_name>` → `brain_tmux_api capture-pane -t <name> -n 50`
- `capture <name> [-n 行数]` → 捕获指定行数（默认 50）
- `panes [-t session]` → 列出 panes

## 示例

```
/tmux agent_system_pmo
/tmux capture agent_xkquant_pmo -n 100
/tmux ls
```
