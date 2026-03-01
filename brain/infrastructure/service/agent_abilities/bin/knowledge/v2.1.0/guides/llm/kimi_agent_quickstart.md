# KIMI Agent 快速创建指南

基于用户验证的最佳实践配置。

## 🚀 快速开始（3 步）

### 1. 创建 Agent 目录

```bash
# 示例：创建一个名为 agent_kimi_coder 的 agent
mkdir -p /brain/groups/org/brain_system/agents/agent_kimi_coder/.claude
cd /brain/groups/org/brain_system/agents/agent_kimi_coder
```

### 2. 复制配置模板

将以下内容保存为 `.claude/settings.local.json`，并替换 `替换为实际agent名` 为你的 agent 名称：

```json
{
  "env": {
    "ANTHROPIC_API_KEY": "替换为KIMI_API_KEY",
    "ANTHROPIC_AUTH_TOKEN": "替换为KIMI_API_KEY",
    "ANTHROPIC_BASE_URL": "https://api.kimi.com/coding/",
    "ANTHROPIC_MODEL": "kimi-for-coding",
    "ANTHROPIC_SMALL_FAST_MODEL": "kimi-for-coding",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "kimi-for-coding",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "kimi-for-coding",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "kimi-for-coding",
    "API_TIMEOUT_MS": "3000000",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"
  },
  "permissions": {
    "allow": [
      "Bash:*:*",
      "Read:*:*",
      "Edit:*:*",
      "Write:*:*",
      "Glob:*:*",
      "Grep:*:*",
      "Task:*:*",
      "Skill:*:*",
      "mcp__*:*",
      "AskUserQuestion:*:*",
      "NotebookEdit:*:*"
    ],
    "defaultMode": "dontAsk"
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|Edit|Glob|Grep|Read|Write",
        "hooks": [
          {
            "type": "command",
            "command": "/brain/infrastructure/service/agent_abilities/hooks/bin/current/pre_tool_use",
            "timeout": 5000
          }
        ]
      }
    ]
  },
  "statusLine": {
    "type": "command",
    "command": "input=$(cat); model=$(echo \"$input\" | jq -r '.model.display_name // \"Claude\"'); dir=$(echo \"$input\" | jq -r '.workspace.current_dir // \"~\"'); used=$(echo \"$input\" | jq -r '.context_window.used_percentage // empty'); if [ -n \"$used\" ]; then printf \"%s | %s | Context: %.1f%% used\" \"$model\" \"$dir\" \"$used\"; else printf \"%s | %s\" \"$model\" \"$dir\"; fi"
  },
  "enabledPlugins": {
    "frontend-design@claude-plugins-official": true,
    "context7@claude-plugins-official": true,
    "ralph-loop@claude-plugins-official": true,
    "feature-dev@claude-plugins-official": true,
    "code-review@claude-plugins-official": true,
    "playwright@claude-plugins-official": true,
    "plugin-dev@claude-plugins-official": true,
    "firebase@claude-plugins-official": true,
    "code-simplifier@claude-plugins-official": true,
    "claude-md-management@claude-plugins-official": true,
    "greptile@claude-plugins-official": true
  },
  "language": "中文",
  "spinnerTipsEnabled": false,
  "skipDangerousModePermissionPrompt": true,
  "mcpServers": {
    "brain-ipc-c": {
      "command": "/brain/infrastructure/service/agent_abilities/mcp/brain_ipc_c/bin/current/brain_ipc_c_mcp_server",
      "args": [],
      "env": {
        "BRAIN_AGENT_NAME": "替换为实际agent名",
        "BRAIN_DAEMON_AUTOSTART": "1"
      }
    }
  }
}
```

### 3. 启动 Agent

```bash
claude --model kimi-for-coding --dangerously-skip-permissions
```

**就这么简单！** 🎉

## 📋 完整配置详解

### settings.local.json 关键字段

```json
{
  "env": {
    // KIMI API 认证
    "ANTHROPIC_API_KEY": "sk-kimi-你的key",

    // KIMI Coding API endpoint（专为编程优化）
    "ANTHROPIC_BASE_URL": "https://api.kimi.com/coding/v1"
  },

  "mcpServers": {
    "brain-ipc-c": {
      "env": {
        // 重要：必须与 agent 名称一致
        "BRAIN_AGENT_NAME": "agent_kimi_coder",
        "BRAIN_TMUX_SESSION": "agent_kimi_coder"
      }
    }
  }
}
```

### KIMI Coding API 特点

| 特性 | 说明 |
|------|------|
| **Endpoint** | `https://api.kimi.com/coding/v1` |
| **模型** | `kimi-for-coding` |
| **优化方向** | 代码生成、理解、审查 |
| **上下文** | 128K tokens |
| **中文支持** | 原生优秀 |

## 🎯 使用场景

### 场景 1: 代码审查 Agent

```bash
# 创建目录
mkdir -p /brain/groups/org/brain_system/agents/agent_kimi_reviewer/.claude

# 复制上面的完整配置（见"快速开始"第2步），替换 "替换为实际agent名" 为 "agent_kimi_reviewer"

# 启动
cd /brain/groups/org/brain_system/agents/agent_kimi_reviewer
claude --model kimi-for-coding --dangerously-skip-permissions
```

### 场景 2: 中文文档 Agent

```bash
# 同样配置，但可以专注于中文文档处理
mkdir -p /brain/groups/org/brain_system/agents/agent_kimi_docs/.claude
# ... (步骤同上)
```

### 场景 3: 通过 agentctl 管理

在 `agents_registry.yaml` 中添加：

```yaml
  - name: agent_kimi_coder
    description: 使用 KIMI Coding API 的开发 Agent
    scope: group
    group: brain_system
    path: /brain/groups/org/brain_system/agents/agent_kimi_coder
    agent_type: claude
    model: kimi-for-coding
    tmux_session: agent_kimi_coder
    cwd: /brain/groups/org/brain_system/agents/agent_kimi_coder
    cli_args:
      - --model
      - kimi-for-coding
      - --dangerously-skip-permissions
    env:
      IS_SANDBOX: 1
    export_cmd:
      BRAIN_AGENT_NAME: agent_kimi_coder
    required: false
    desired_state: STOPPED
    status: STOPPED
    capabilities:
      - code_generation
      - code_review
      - chinese_documentation
    tags:
      - kimi
      - coder
      - chinese
```

然后使用 agentctl 启动：
```bash
/brain/infrastructure/service/agent-ctl/bin/agentctl start agent_kimi_coder --apply
```

## 🔧 验证配置

### 测试 API 连接

```bash
# 加载环境变量
source /brain/runtime/config/.env

# 测试 KIMI Coding API
curl -s https://api.kimi.com/coding/v1/messages \
  -H "content-type: application/json" \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "kimi-for-coding",
    "messages": [{"role": "user", "content": "写一个 Python 快速排序"}],
    "max_tokens": 500
  }' | jq '.content[0].text'
```

### 手动启动测试

```bash
cd /brain/groups/org/brain_system/agents/agent_kimi_coder

# 方式 1: 使用 --model 参数
claude --model kimi-for-coding --dangerously-skip-permissions

# 方式 2: settings.local.json 中已设置 model
claude --dangerously-skip-permissions
```

## 📊 与其他方案对比

| 方案 | 配置复杂度 | 性能 | 稳定性 | 推荐度 |
|------|-----------|------|--------|--------|
| **settings.local.json** ✅ | ⭐ 简单 | ⭐⭐⭐ 最快 | ⭐⭐⭐ 最稳定 | ⭐⭐⭐⭐⭐ |
| LiteLLM Proxy | ⭐⭐⭐ 复杂 | ⭐⭐ 多一层 | ⭐⭐ 依赖进程 | ⭐⭐ |
| 环境变量 | ⭐⭐ 中等 | ⭐⭐⭐ 快 | ⭐⭐⭐ 稳定 | ⭐⭐⭐ |

## 🎨 CLAUDE.md 示例

创建 `CLAUDE.md` 文件：

```markdown
---
role: KIMI Coding Agent
version: 1.0
location: /brain/groups/org/brain_system/agents/agent_kimi_coder
scope: brain_system
---

# agent_kimi_coder 配置

## 模型信息

- **提供商**: Kimi (月之暗面)
- **API**: https://api.kimi.com/coding/v1
- **模型**: kimi-for-coding (专为编程优化)
- **上下文**: 128K tokens
- **特点**: 中文原生支持，代码生成优秀

## 核心能力

1. **代码生成**: Python, JavaScript, Go, Rust 等
2. **代码审查**: 发现潜在问题，提供改进建议
3. **中文文档**: 生成清晰的中文注释和文档
4. **架构设计**: 系统设计和技术选型建议

## IPC 通信

启动后立即：
1. `ipc_register(agent_name="agent_kimi_coder")`
2. `ipc_recv(ack_mode="manual", max_items=10)`
3. 处理消息并回复
```

## 🚨 常见问题

### Q: 启动时提示 "Nested sessions"

**A**: 不能在现有 Claude Code session 中启动新 session。
```bash
# 解决方法：使用 tmux
tmux new-session -s agent_kimi_coder
cd /brain/groups/org/brain_system/agents/agent_kimi_coder
claude --model kimi-for-coding --dangerously-skip-permissions
```

### Q: API key 认证失败

**A**: 检查 `.claude/settings.local.json` 中的 API key 是否正确。
```bash
cat .claude/settings.local.json | jq '.env.ANTHROPIC_API_KEY'
```

### Q: 如何切换回标准 Claude？

**A**: 删除或重命名 `settings.local.json`：
```bash
mv .claude/settings.local.json .claude/settings.local.json.bak
```

### Q: 如何查看实际使用的模型？

**A**: 在 agent 对话中：
```
请告诉我你当前使用的模型是什么？
```

## 📚 相关文档

- KIMI API 文档: https://platform.kimi.ai/docs
- Claude Code 文档: https://docs.anthropic.com/claude-code
- Agent 协议: `/brain/base/spec/policies/agents/agent_protocol.yaml`
- 完整配置: 见上文"快速开始"第2步

## 🎯 下一步

1. ✅ 验证 KIMI API key
2. ✅ 创建 agent 目录和配置
3. ✅ 手动启动测试
4. ✅ 配置 CLAUDE.md
5. ✅ 注册到 agents_registry.yaml
6. ✅ 使用 agentctl 管理
7. ✅ 测试 IPC 通信

---

**最后更新**: 2026-02-13
**验证者**: 用户实测配置
