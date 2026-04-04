---
id: G-SKILL-TELEGRAM
name: telegram
description: "通过 Telegram Bot 向用户发送通知、请求审批、等待用户响应。不要直接调用 Telegram API；通过 IPC 发给 service-telegram_api，或使用 ipc skill 的 notify 快捷方式。"
user-invocable: true
disable-model-invocation: false
allowed-tools: mcp__mcp-brain_ipc_c__ipc_send
argument-hint: "[notify|approve|wait] <message>"
metadata:
  status: active
  source_project: /xkagent_infra/brain/base/skill/telegram
  version: "1.0.0"
---

# telegram — 用户通知与审批

通过 Telegram Bot 与用户交互。所有消息都通过 `service-telegram_api` 发送，不直接调用 Telegram API。

## 三种使用场景

### 1. 单向通知（不等回复）

```python
ipc_send(
    to="service-telegram_api",
    message="[TASK_DONE] 项目 BS-029 所有任务已完成，等待验收",
    priority="normal"
)
```

### 2. 请求审批（等用户决策）

```python
ipc_send(
    to="service-telegram_api",
    message="[APPROVAL_REQUEST] 项目 BS-029 需要 Go/No-Go 决策\n\n方案：重构认证模块\n影响：需要停服 10 分钟\n\n请回复：1=Go，2=No-Go",
    priority="high",
    message_type="request"
)
# 然后 ipc_recv 等待回复（service-telegram_api 会转发用户的回复给你）
```

### 3. 告警（立即引起注意）

```python
ipc_send(
    to="service-telegram_api",
    message="[ALERT] agent-brain_dev 不可恢复错误\n错误：数据库连接失败\n已停止执行，等待人工介入",
    priority="critical"
)
```

## 消息前缀规范

| 前缀 | 场景 | 优先级 |
|------|------|--------|
| `[TASK_DONE]` | 任务/项目完成 | normal |
| `[PROGRESS]` | 阶段进展汇报 | low |
| `[APPROVAL_REQUEST]` | 需要用户决策 | high |
| `[BUILD]` | 构建/部署状态 | high |
| `[ALERT]` | 严重错误/阻塞 | critical |
| `[NOTIFY]` | 一般通知 | normal |

## 重要约束

- **不要绕过 PMO 直接通知用户**：需要用户审批时，先发给 PMO（`agent-brain_pmo`），由 PMO 决定是否升级给用户。只有 PMO、Manager、Frontdesk 才应直接使用 telegram skill。
- **不要轮询**：发出 approval request 后用 `ipc_recv(wait_seconds=3600)` 等，不要循环发送。
- **Markdown 支持**：消息支持 Telegram Markdown，用 `**bold**`、`_italic_`、`` `code` ``。

## 消息格式模板

**任务完成**：
```
[TASK_DONE] {项目/任务名}

✅ 已完成：{完成内容一句话}
📦 交付物：{文件路径或链接}
⏱ 耗时：{时间}
```

**审批请求**：
```
[APPROVAL_REQUEST] {需要决策的事项}

📋 背景：{为什么需要决策}
🎯 方案：{具体方案}
⚠️ 影响：{风险和影响范围}

请回复选项：
1️⃣ 同意
2️⃣ 拒绝
3️⃣ 需要更多信息
```

**告警**：
```
[ALERT] ⚠️ {告警标题}

Agent: {agent_name}
错误: {error_message}
状态: 已停止执行

需要人工介入。
```

## 详细文档

- API 规范：`/xkagent_infra/brain/base/skill/telegram/api.yaml`
- 消息模板：`/xkagent_infra/brain/base/skill/telegram/templates.yaml`
- 使用示例：`/xkagent_infra/brain/base/skill/telegram/examples.yaml`
