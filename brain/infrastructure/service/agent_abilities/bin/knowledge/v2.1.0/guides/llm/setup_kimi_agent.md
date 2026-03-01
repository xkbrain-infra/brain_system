# 创建使用 KIMI API 的 Agent 完整指南

## 架构说明

```
┌─────────────────┐
│  Codex Agent    │
│  (agent_kimi)   │
└────────┬────────┘
         │
         │ OpenAI-compatible API
         ▼
┌─────────────────┐
│ LiteLLM Proxy   │  ← 统一 LLM gateway
│  (localhost)    │
└────────┬────────┘
         │
         │ KIMI API
         ▼
┌─────────────────┐
│  Moonshot API   │
│  (KIMI 服务)    │
└─────────────────┘
```

## 步骤 1: 配置 KIMI API Secrets

### 1.1 创建配置文件

```bash
cd /brain/secrets/system/agents
cp llm_tokens.env.example llm_tokens.env
chmod 600 llm_tokens.env
```

### 1.2 编辑配置

```bash
vim llm_tokens.env
```

填入你的 KIMI API key：

```env
# Kimi (月之暗面)
KIMI_API_KEY=sk-你的实际KIMI_API_KEY
KIMI_API_BASE=https://api.moonshot.cn/v1
KIMI_MODEL=moonshot-v1-32k
```

### 1.3 加载配置

```bash
/brain/infrastructure/launch/loader_env_vars.py --reload

# 验证
grep KIMI /brain/runtime/config/.env
```

## 步骤 2: 安装 LiteLLM

### 2.1 安装 Python 包

```bash
pip install 'litellm[proxy]'
```

### 2.2 创建 LiteLLM 配置目录

```bash
mkdir -p /brain/infrastructure/service/litellm-proxy
cd /brain/infrastructure/service/litellm-proxy
```

### 2.3 创建 LiteLLM 配置文件

创建 `config.yaml`：

```yaml
model_list:
  # Kimi Models
  - model_name: kimi-8k
    litellm_params:
      model: moonshot/moonshot-v1-8k
      api_base: https://api.moonshot.cn/v1
      api_key: os.environ/KIMI_API_KEY

  - model_name: kimi-32k
    litellm_params:
      model: moonshot/moonshot-v1-32k
      api_base: https://api.moonshot.cn/v1
      api_key: os.environ/KIMI_API_KEY

  - model_name: kimi-128k
    litellm_params:
      model: moonshot/moonshot-v1-128k
      api_base: https://api.moonshot.cn/v1
      api_key: os.environ/KIMI_API_KEY

  # MiniMax Models (可选)
  - model_name: minimax-chat
    litellm_params:
      model: minimax/abab5.5-chat
      api_base: https://api.minimax.chat/v1
      api_key: os.environ/MINIMAX_API_KEY

# 通用设置
general_settings:
  master_key: sk-brain-litellm-proxy-2026  # 内部访问密钥
  database_url: "sqlite:////brain/infrastructure/service/litellm-proxy/litellm.db"

litellm_settings:
  drop_params: true  # 自动过滤不支持的参数
  success_callback: ["langfuse"]  # 可选：添加监控

router_settings:
  routing_strategy: simple-shuffle  # 负载均衡策略
  num_retries: 3
  timeout: 600
```

### 2.4 创建启动脚本

创建 `start_litellm.sh`：

```bash
#!/bin/bash
set -e

# 加载环境变量
source /brain/runtime/config/.env

# 启动 LiteLLM proxy
litellm --config /brain/infrastructure/service/litellm-proxy/config.yaml \
  --port 8000 \
  --host 0.0.0.0 \
  --detailed_debug
```

```bash
chmod +x start_litellm.sh
```

### 2.5 创建 systemd 服务（可选，生产环境）

创建 `/etc/systemd/system/litellm-proxy.service`：

```ini
[Unit]
Description=LiteLLM Proxy Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/brain/infrastructure/service/litellm-proxy
Environment="PATH=/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=/brain/runtime/config/.env
ExecStart=/brain/infrastructure/service/litellm-proxy/start_litellm.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
systemctl daemon-reload
systemctl enable litellm-proxy
systemctl start litellm-proxy
systemctl status litellm-proxy
```

### 2.6 测试 LiteLLM Proxy

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-brain-litellm-proxy-2026" \
  -d '{
    "model": "kimi-32k",
    "messages": [
      {"role": "user", "content": "你好，请用一句话介绍你自己"}
    ]
  }'
```

## 步骤 3: 创建使用 KIMI 的 Agent

### 3.1 创建 Agent 目录结构

```bash
# 使用 add-agent skill（推荐）
cd /brain
claude

# 在 Claude 中执行
/add-agent
```

或者手动创建：

```bash
mkdir -p /brain/groups/org/brain_system/agents/agent_kimi_demo/{.codex,.claude}
chmod 700 /brain/groups/org/brain_system/agents/agent_kimi_demo
```

### 3.2 创建 Codex 配置

创建 `/brain/groups/org/brain_system/agents/agent_kimi_demo/.codex/config.toml`：

```toml
# 使用 LiteLLM proxy 提供的 KIMI 模型
model = "kimi-32k"
model_reasoning_effort = "medium"
profile = "kimi"
suppress_unstable_features_warning = true

[projects."/brain/groups/org/brain_system/agents/agent_kimi_demo"]
trust_level = "trusted"

[profiles.kimi]
approval_policy = "never"
sandbox_mode = "danger-full-access"
model = "kimi-32k"
model_reasoning_effort = "medium"

# 配置自定义 API endpoint（指向 LiteLLM proxy）
[api]
base_url = "http://localhost:8000/v1"
api_key = "sk-brain-litellm-proxy-2026"

[features]
unified_exec = true
shell_snapshot = true
steer = true
multi_agent = true
apps = true

# IPC MCP Server
[mcp_servers.brain-ipc-c]
command = "/brain/runtime/engine/src/mcp/brain_ipc_c/brain_ipc_c_mcp_server"
args = []
env = { BRAIN_AGENT_NAME = "agent_kimi_demo", BRAIN_TMUX_SESSION = "agent_kimi_demo" }
```

### 3.3 创建 Agent 指令文档

创建 `/brain/groups/org/brain_system/agents/agent_kimi_demo/AGENTS.md`：

```markdown
---
role: KIMI 驱动的演示 Agent
version: 1.0
location: /brain/groups/org/brain_system/agents/agent_kimi_demo
scope: brain_system
---

# agent_kimi_demo 配置

## 职责定位

**我是使用 KIMI API 的演示 Agent**，用于验证 KIMI 模型集成和测试中文 LLM 能力。

## LLM 配置

- **模型**: Moonshot KIMI (moonshot-v1-32k)
- **API 提供商**: 月之暗面 (Moonshot AI)
- **上下文长度**: 32K tokens
- **通过**: LiteLLM Proxy (localhost:8000)

## 初始化序列

```yaml
init_sequence:
  1:
    action: register_agent
    params:
      agent_name: agent_kimi_demo
      metadata:
        role: kimi_demo
        model: kimi-32k
        provider: moonshot
        scope: brain_system
        status: active

  2:
    action: activate_ipc
    params:
      ack_mode: manual
      max_batch: 10

  3:
    action: load_core_refs
    refs:
      - /brain/INIT.yaml
      - /brain/base/spec/core/lep.yaml
      - /brain/base/spec/policies/ipc/message_format.yaml
```

## 核心规则

### IPC 通信

1. 启动后立即调用 `ipc_register(agent_name="agent_kimi_demo")`
2. 使用 `ipc_recv(ack_mode="manual", wait_seconds=30)` 接收消息
3. 处理后必须 `ipc_ack(msg_ids=[...])`
4. 回复使用 `ipc_send(to="sender", message="...", message_type="response")`

### 任务执行

- 使用中文进行沟通
- 利用 KIMI 的长上下文能力处理大文件
- 测试中文理解和生成能力

## 测试任务

启动后可以测试：

1. **中文理解**: 分析中文代码和文档
2. **长文本处理**: 处理超过 10K tokens 的文档
3. **代码生成**: 生成带中文注释的代码
4. **IPC 协作**: 与其他 agent 协同工作
```

### 3.4 注册到 agents_registry.yaml

编辑 `/brain/groups/org/brain_system/projects/agent_orchestrator/config/agents_registry.yaml`，添加：

```yaml
  - name: agent_kimi_demo
    description: 使用 KIMI API 的演示 Agent - 测试中文 LLM 集成
    scope: group
    group: brain_system
    path: /brain/groups/org/brain_system/agents/agent_kimi_demo
    agent_type: codex
    model: kimi-32k  # 通过 LiteLLM proxy
    tmux_session: agent_kimi_demo
    cwd: /brain/groups/org/brain_system/agents/agent_kimi_demo
    cli_args:
      - --dangerously-skip-permissions
      - --model
      - kimi-32k
    env:
      IS_SANDBOX: 1
      LITELLM_API_BASE: http://localhost:8000/v1
      LITELLM_API_KEY: sk-brain-litellm-proxy-2026
    export_cmd:
      BRAIN_AGENT_NAME: agent_kimi_demo
    initial_prompt: "agent_kimi_demo"
    config:
      config_home: /brain/groups/org/brain_system/agents/agent_kimi_demo/.codex
      mcp_config: /brain/groups/org/brain_system/agents/agent_kimi_demo/.codex/.mcp.json
    required: false
    desired_state: STOPPED
    status: STOPPED
    capabilities:
      - chinese_llm
      - long_context
      - ipc_communication
    tags:
      - demo
      - kimi
      - chinese
```

## 步骤 4: 启动 Agent

### 4.1 确保 LiteLLM Proxy 运行

```bash
# 如果使用 tmux
tmux new-session -d -s litellm-proxy
tmux send-keys -t litellm-proxy "cd /brain/infrastructure/service/litellm-proxy" C-m
tmux send-keys -t litellm-proxy "source /brain/runtime/config/.env" C-m
tmux send-keys -t litellm-proxy "./start_litellm.sh" C-m

# 检查状态
curl http://localhost:8000/health
```

### 4.2 启动 Agent

```bash
# 使用 agentctl
/brain/infrastructure/service/agent-ctl/bin/agentctl start agent_kimi_demo --apply

# 检查状态
tmux attach -t agent_kimi_demo
```

### 4.3 测试 Agent

通过 IPC 发送测试消息：

```python
# 在另一个 agent 或脚本中
from brain_ipc_c_mcp_server import ipc_send

ipc_send(
    to="agent_kimi_demo",
    message="你好！请用中文介绍一下你自己，说明你使用的是什么模型。",
    priority="normal"
)
```

## 步骤 5: 监控和调试

### 5.1 查看 LiteLLM 日志

```bash
# 如果用 systemd
journalctl -u litellm-proxy -f

# 如果用 tmux
tmux attach -t litellm-proxy
```

### 5.2 查看 Agent 日志

```bash
# Agent 会话
tmux attach -t agent_kimi_demo

# 全局日志
tail -f /brain/runtime/logs/agents/global_agent_log_$(date +%Y-%m-%d).jsonl | jq .
```

### 5.3 检查 API 使用情况

LiteLLM 提供 UI 界面（可选）：

```bash
# 在 config.yaml 中启用 UI
litellm --config config.yaml --port 8000 --ui
```

访问 http://localhost:8000 查看 dashboard。

## 常见问题

### Q1: Codex 无法连接到 LiteLLM proxy

**症状**: `Connection refused` 或 `404 Not Found`

**解决**:
```bash
# 检查 LiteLLM 是否运行
curl http://localhost:8000/health

# 检查端口
netstat -tlnp | grep 8000

# 重启 LiteLLM
systemctl restart litellm-proxy
```

### Q2: KIMI API 返回 401 Unauthorized

**症状**: `Invalid API key`

**解决**:
```bash
# 验证 API key
grep KIMI_API_KEY /brain/runtime/config/.env

# 重新加载配置
/brain/infrastructure/launch/loader_env_vars.py --reload

# 重启 LiteLLM
systemctl restart litellm-proxy
```

### Q3: Agent 启动失败

**症状**: tmux session 立即退出

**解决**:
```bash
# 检查 Codex 配置
cat /brain/groups/org/brain_system/agents/agent_kimi_demo/.codex/config.toml

# 手动测试启动
cd /brain/groups/org/brain_system/agents/agent_kimi_demo
codex --model kimi-32k --dangerously-skip-permissions
```

### Q4: KIMI 响应慢或超时

**解决**:
- 调整 LiteLLM timeout: `config.yaml` 中增加 `timeout: 600`
- 使用更快的模型: `kimi-8k` 代替 `kimi-32k`
- 检查网络连接到 Moonshot API

## 成本优化

### 模型选择策略

```yaml
# 简单任务用 8K
simple_tasks: kimi-8k  # 更便宜、更快

# 中等任务用 32K
normal_tasks: kimi-32k  # 平衡

# 长文本分析用 128K
long_context: kimi-128k  # 最贵但支持超长上下文
```

### 缓存配置

在 LiteLLM config.yaml 中启用缓存：

```yaml
litellm_settings:
  cache: true
  cache_params:
    type: redis
    host: localhost
    port: 6379
```

## 扩展方案

### 支持更多模型

编辑 `/brain/infrastructure/service/litellm-proxy/config.yaml`：

```yaml
model_list:
  # 添加其他国产模型
  - model_name: glm-4
    litellm_params:
      model: zhipuai/glm-4
      api_key: os.environ/ZHIPU_API_KEY

  - model_name: qwen-max
    litellm_params:
      model: alibaba/qwen-max
      api_key: os.environ/QWEN_API_KEY
```

### 负载均衡

配置多个 KIMI API keys 实现负载均衡：

```yaml
model_list:
  - model_name: kimi-32k
    litellm_params:
      model: moonshot/moonshot-v1-32k
      api_key: os.environ/KIMI_API_KEY_1

  - model_name: kimi-32k
    litellm_params:
      model: moonshot/moonshot-v1-32k
      api_key: os.environ/KIMI_API_KEY_2
```

## 参考链接

- KIMI API 文档: https://platform.moonshot.cn/docs
- LiteLLM 文档: https://docs.litellm.ai/
- Codex 配置: `/brain/groups/org/brain_system/agents/agent-system_architect/.codex/config.toml`
- Agent Registry: `/brain/groups/org/brain_system/projects/agent_orchestrator/config/agents_registry.yaml`
