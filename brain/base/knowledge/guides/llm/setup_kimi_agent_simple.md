# 使用 KIMI 的 Agent - 简化方案

## 重要发现

KIMI (Moonshot) 提供了 **Anthropic API 兼容接口**，这意味着：
- ✅ 不需要 LiteLLM Proxy
- ✅ 直接使用 Claude Code
- ✅ 配置更简单
- ✅ 性能更好（少一层代理）

## 快速开始

### 方法 1: 使用环境变量启动

```bash
# 1. 设置环境变量
export ANTHROPIC_API_KEY=sk-kimi-你的key
export ANTHROPIC_BASE_URL=https://api.moonshot.cn/anthropic/

# 2. 启动 Claude Code
cd /brain/groups/org/brain_system/agents/agent_kimi_demo
claude --dangerously-skip-permissions

# KIMI 模型会自动被识别为 Claude，但实际调用 KIMI API
```

### 方法 2: 在 Agent Registry 中配置

编辑 `agents_registry.yaml`：

```yaml
  - name: agent_kimi_demo
    description: 使用 KIMI API 的 Agent
    scope: group
    group: brain_system
    path: /brain/groups/org/brain_system/agents/agent_kimi_demo
    agent_type: claude  # 使用 claude 类型！
    model: Sonnet       # 模型名（会被 KIMI 接管）
    tmux_session: agent_kimi_demo
    cwd: /brain/groups/org/brain_system/agents/agent_kimi_demo
    cli_args:
      - --dangerously-skip-permissions
    env:
      IS_SANDBOX: 1
      # 关键：设置 KIMI 环境变量
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      ANTHROPIC_BASE_URL: https://api.moonshot.cn/anthropic/
    export_cmd:
      BRAIN_AGENT_NAME: agent_kimi_demo
    initial_prompt: "agent_kimi_demo"
    hooks:
      - pre_tool_use
      - post_tool_use
    config:
      config_home: /brain/groups/org/brain_system/agents/agent_kimi_demo/.claude
      mcp_config: /brain/groups/org/brain_system/agents/agent_kimi_demo/.mcp.json
    required: false
    desired_state: STOPPED
    status: STOPPED
```

### 方法 3: 使用 agentctl 启动脚本

创建启动脚本 `/brain/groups/org/brain_system/agents/agent_kimi_demo/start_with_kimi.sh`：

```bash
#!/bin/bash
set -e

# 加载 KIMI API 配置
source /brain/runtime/config/.env

# 启动 Claude Code with KIMI API
cd /brain/groups/org/brain_system/agents/agent_kimi_demo
exec claude --dangerously-skip-permissions
```

## Agent 目录结构

```
/brain/groups/org/brain_system/agents/agent_kimi_demo/
├── .claude/                    # Claude Code 配置目录
│   └── memory/                 # Agent 记忆（可选）
├── .mcp.json                   # MCP servers 配置
├── CLAUDE.md                   # Agent 指令文档
├── start_with_kimi.sh         # 启动脚本（可选）
└── README.md                   # Agent 说明
```

## CLAUDE.md 示例

```markdown
---
role: KIMI 驱动的中文助手
version: 1.0
location: /brain/groups/org/brain_system/agents/agent_kimi_demo
scope: brain_system
---

# agent_kimi_demo 配置

## 职责定位

我是使用 **KIMI (Moonshot AI)** 模型的 Agent，专注于中文任务处理。

## 模型信息

- **提供商**: Moonshot AI (月之暗面)
- **模型**: moonshot-v1-32k (32K 上下文)
- **API**: Anthropic 兼容接口
- **特点**:
  - 中文理解和生成优秀
  - 32K 上下文窗口
  - 支持长文档分析

## 初始化序列

启动后立即：
1. 注册 IPC: `ipc_register(agent_name="agent_kimi_demo")`
2. 激活消息接收: `ipc_recv(ack_mode="manual")`
3. 加载核心规范: `/brain/INIT.yaml`, `/brain/base/spec/core/lep.yaml`

## 核心能力

1. **中文任务处理**
   - 中文代码审查
   - 中文文档生成
   - 中文需求分析

2. **长文本处理**
   - 利用 32K 上下文
   - 完整文档分析
   - 多文件关联理解

3. **协作能力**
   - IPC 消息通信
   - 与其他 agents 协作
   - 任务分发和聚合
```

## .mcp.json 配置

```json
{
  "mcpServers": {
    "brain-ipc-c": {
      "command": "/brain/infrastructure/service/agent_abilities/mcp/brain_ipc_c/bin/current/brain_ipc_c_mcp_server",
      "args": [],
      "env": {
        "BRAIN_AGENT_NAME": "agent_kimi_demo",
        "BRAIN_TMUX_SESSION": "agent_kimi_demo"
      }
    }
  }
}
```

## 验证 KIMI API

在创建 agent 前，验证 API 可用性：

```bash
# 加载环境变量
source /brain/runtime/config/.env

# 测试 KIMI API
curl -s https://api.moonshot.cn/anthropic/v1/messages \
  -H "content-type: application/json" \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "moonshot-v1-8k",
    "messages": [{"role": "user", "content": "你好"}],
    "max_tokens": 50
  }' | jq .
```

预期响应：
```json
{
  "content": [
    {
      "text": "你好！我是 Kimi...",
      "type": "text"
    }
  ],
  "model": "moonshot-v1-8k",
  "role": "assistant",
  ...
}
```

## 启动 Agent

### 手动启动

```bash
cd /brain/groups/org/brain_system/agents/agent_kimi_demo

# 方式 1: 直接启动
export ANTHROPIC_API_KEY=sk-kimi-你的key
export ANTHROPIC_BASE_URL=https://api.moonshot.cn/anthropic/
claude --dangerously-skip-permissions

# 方式 2: 使用启动脚本
./start_with_kimi.sh
```

### 通过 agentctl

```bash
# 确保 agents_registry.yaml 已配置
/brain/infrastructure/service/agent-ctl/bin/agentctl start agent_kimi_demo --apply

# 查看状态
tmux attach -t agent_kimi_demo
```

## 常见问题

### Q: KIMI 和 Claude 有什么区别？

**A**: 从 agent 角度看：
- API 调用格式完全相同（Anthropic 兼容）
- 配置方式相同
- 区别仅在于 `ANTHROPIC_BASE_URL` 指向 KIMI

**实际差异**：
- KIMI: 中文能力更强，32K 上下文，成本较低
- Claude: 英文能力更强，200K 上下文，成本较高

### Q: 能否在同一个系统中混用 KIMI 和 Claude agents？

**A**: 可以！
- Claude agents: 不设置 `ANTHROPIC_BASE_URL`（使用默认）
- KIMI agents: 设置 `ANTHROPIC_BASE_URL=https://api.moonshot.cn/anthropic/`

### Q: KIMI API 收费标准？

**A**: 参考 Moonshot 平台定价（2026-02-13）：
- moonshot-v1-8k: ¥0.012/千 tokens（输入）
- moonshot-v1-32k: ¥0.024/千 tokens（输入）
- moonshot-v1-128k: ¥0.06/千 tokens（输入）

### Q: KIMI 支持哪些模型？

**A**: 通过 Anthropic 兼容 API：
- `moonshot-v1-8k` - 8K 上下文
- `moonshot-v1-32k` - 32K 上下文
- `moonshot-v1-128k` - 128K 上下文

注意：模型名在 API 调用时指定，但 Claude Code 会自动使用默认模型。

## 性能优化

### 上下文管理

KIMI 32K 上下文建议：
- 单轮对话: < 4K tokens（留出输出空间）
- 多轮对话: 监控累计 tokens，必要时总结
- 长文档: 使用 128K 模型

### 成本控制

```yaml
cost_optimization:
  simple_tasks: moonshot-v1-8k   # 简单问答
  normal_tasks: moonshot-v1-32k   # 代码审查、文档分析
  complex_tasks: moonshot-v1-128k # 超长文档、完整代码库分析
```

## 故障排查

### API 认证失败

```bash
# 检查环境变量
echo $ANTHROPIC_API_KEY
echo $ANTHROPIC_BASE_URL

# 重新加载配置
source /brain/runtime/config/.env
```

### Agent 无法启动

```bash
# 检查 tmux session
tmux list-sessions | grep agent_kimi_demo

# 查看日志
tmux capture-pane -t agent_kimi_demo -p | tail -50
```

### IPC 通信失败

```bash
# 验证 MCP 配置
cat .mcp.json | jq .

# 检查 daemon
ps aux | grep brain_ipc
```

## 下一步

- ✅ 验证 KIMI API key
- ✅ 创建 agent 目录结构
- ✅ 配置 CLAUDE.md 和 .mcp.json
- ✅ 注册到 agents_registry.yaml
- ✅ 使用 agentctl 启动
- ✅ 测试 IPC 通信
- ✅ 与其他 agents 协作

## 参考资源

- KIMI API 文档: https://platform.moonshot.cn/docs
- Anthropic API 规范: https://docs.anthropic.com/claude/reference
- Brain Agent 协议: `/brain/base/spec/policies/agents/agent_protocol.yaml`
- Agent 模板: `/brain/base/spec/templates/agent/base_template.md`
