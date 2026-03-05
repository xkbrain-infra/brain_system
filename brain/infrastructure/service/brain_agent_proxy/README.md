# brain_agent_proxy

自研统一代理网关，完全掌控协议路由与 provider 接入。

## 功能

- **多协议路由**：
  - `/v1/messages` (Claude Code)
  - `/v1/chat/completions` (OpenAI 兼容)
  - `/v1/responses` (Codex - 部分支持)
- **Provider 接入**：
  - GitHub Copilot (OAuth Device)
  - OpenAI (API Key)
  - Anthropic (API Key)
  - Gemini (API Key / OAuth PKCE)
  - MiniMax (API Key)
- **路由策略**：capability_match, cost_weighted, availability
- **观测**：健康检查、模型列表
- **Copilot 能力对齐（非 CLI）**：
  - `/usage`、`/check-usage`、`/token`、`/debug`
  - `/v1/messages/count_tokens`
  - 模型不可用自动降级（例如 `gpt-5-mini -> gpt-4o`）
  - 服务端限流与手动审批（环境变量开关）

## 快速开始

### 启动服务

```bash
brain_agent_proxy start --port 3456
```

### 测试

```bash
brain_agentctl test
```

### 启用代理（Claude Code）

在 `.claude/settings.local.json` 的 `env` 部分添加：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:3456",
    "ANTHROPIC_AUTH_TOKEN": "bgw-apx-v1--p-openai--m-gpt_5_mini--n-dev",
    "ANTHROPIC_MODEL": "openai/gpt-5-mini"
  }
}
```

命名规范：
- `ANTHROPIC_AUTH_TOKEN`: `bgw-apx-v1--p-{provider}--m-{model_key}--n-{name}`
- `ANTHROPIC_MODEL`: `provider/model`
- 兼容性：历史 `proxy-{provider}_{model}_{name}` 仍可用（建议迁移到新格式）

## 命令

### brain_agent_proxy

```bash
brain_agent_proxy start --port 3456          # 启动
brain_agent_proxy stop                        # 停止
brain_agent_proxy restart                     # 重启
brain_agent_proxy status                     # 状态
brain_agent_proxy health                      # 健康检查
```

### brain_agentctl

```bash
brain_agentctl status                        # 查看状态
brain_agentctl enable                        # 输出配置片段
brain_agentctl disable                       # 输出禁用说明
brain_agentctl test                          # 测试请求
brain_agentctl auth list                     # 查看 OAuth provider 授权状态
brain_agentctl auth status                   # 查看全部 provider token 状态
brain_agentctl auth status --provider gemini # 查看单个 provider token 状态
brain_agentctl auth --provider openai        # OpenAI 设备码授权 (login)
brain_agentctl auth --provider gemini        # Gemini OAuth PKCE 授权 (默认手动粘贴 code)
brain_agentctl auth --provider gemini --auto-callback # Gemini OAuth PKCE 自动本地回调收码
brain_agentctl auth logout --provider gemini # 删除单个 provider token
brain_agentctl auth logout --all             # 删除所有 OAuth token
```

## API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/v1/models` | GET | 可用模型列表 |
| `/v1/messages` | POST | Claude Code 协议 |
| `/v1/messages/count_tokens` | POST | Anthropic token 预估 |
| `/v1/chat/completions` | POST | OpenAI 协议 |
| `/v1/responses` | POST | Codex 协议 (部分支持) |
| `/v1/embeddings` | POST | Embeddings |
| `/usage` | GET | Copilot usage |
| `/check-usage` | GET | usage 别名（对齐 copilot-api） |
| `/v1/usage` | GET | usage 命名空间别名 |
| `/token` | GET | 当前 Copilot token（调试） |
| `/debug` | GET | 运行时诊断信息 |
| `/approvals` | GET | 手动审批队列 |
| `/approvals/{id}/approve` | POST | 通过请求 |
| `/approvals/{id}/deny` | POST | 拒绝请求 |

## 配置

### Providers

编辑 `config/providers.yaml`：

```yaml
providers:
  - id: copilot-default
    type: oauth_device
    models:
      - gpt-5-mini
      - gpt-5.2-codex
    cli_type: chat_completions
    enabled: true
```

### 路由策略

编辑 `config/routing.yaml`：

```yaml
routing:
  default_strategy: capability_match
  model_strategy_map:
    gpt-5-mini: cost_weighted
```

### 服务端策略（非 CLI）

通过环境变量控制（建议写入 supervisor 环境）：

```bash
# 全局请求最小间隔秒数；0 表示关闭
export BRAIN_AGENT_PROXY_RATE_LIMIT_SECONDS=0
# 命中限流时是否等待；0=直接429，1=等待
export BRAIN_AGENT_PROXY_RATE_LIMIT_WAIT=1

# 手动审批开关；1=每个请求需审批
export BRAIN_AGENT_PROXY_MANUAL_APPROVAL=0
# 审批超时秒数
export BRAIN_AGENT_PROXY_MANUAL_APPROVAL_TIMEOUT_SECONDS=300
```

## 文件结构

```
brain_agent_proxy/
├── bin/
│   ├── brain_agent_proxy        # 服务管理脚本
│   └── brain_agentctl           # 配置管理工具
├── src/
│   ├── main.py                  # FastAPI 应用
│   ├── config.py                # 配置加载
│   ├── protocol/                # 协议处理
│   ├── routing/                  # 路由引擎
│   ├── providers/               # Provider 适配
│   ├── auth/                    # 认证
│   └── observability/           # 观测
├── config/
│   ├── providers.yaml           # Provider 配置
│   └── routing.yaml             # 路由配置
└── README.md
```

## 限制

- `/v1/responses` 协议依赖上游 provider 支持
- 部分 provider 需要配置 API Key 环境变量
