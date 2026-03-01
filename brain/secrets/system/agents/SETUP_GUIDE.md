# Agent LLM Tokens 配置指南

## 快速开始

### 1. 创建配置文件

```bash
cd /brain/secrets/system/agents
cp llm_tokens.env.example llm_tokens.env
chmod 600 llm_tokens.env
```

### 2. 编辑配置文件

```bash
vim llm_tokens.env
```

填入实际的 API keys：

```env
# Kimi
KIMI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
KIMI_API_BASE=https://api.moonshot.cn/v1
KIMI_MODEL=moonshot-v1-8k

# MiniMax
MINIMAX_API_KEY=eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...
MINIMAX_GROUP_ID=1234567890
MINIMAX_API_BASE=https://api.minimax.chat/v1
MINIMAX_MODEL=abab5.5-chat
```

### 3. 加载配置

```bash
/brain/infrastructure/launch/loader_env_vars.py --reload
```

### 4. 验证配置

```bash
# 检查运行时配置
grep -E 'KIMI|MINIMAX' /brain/runtime/config/.env

# 查看配置来源
cat /brain/runtime/config/sources.yaml | grep -A 5 agents
```

## 支持的 LLM 服务商

### 月之暗面 Kimi

- 官网: https://platform.moonshot.cn/
- 文档: https://platform.moonshot.cn/docs/api
- 获取 API Key: https://platform.moonshot.cn/console/api-keys

**可用模型**:
- `moonshot-v1-8k` - 8K 上下文
- `moonshot-v1-32k` - 32K 上下文
- `moonshot-v1-128k` - 128K 上下文

**环境变量**:
```env
KIMI_API_KEY=sk-...
KIMI_API_BASE=https://api.moonshot.cn/v1
KIMI_MODEL=moonshot-v1-8k
```

### MiniMax

- 官网: https://www.minimaxi.com/
- 文档: https://www.minimaxi.com/document/introduction
- 获取 API Key: https://www.minimaxi.com/user-center/basic-information

**可用模型**:
- `abab5.5-chat` - 最新对话模型
- `abab5.5s-chat` - 更快速的版本
- `abab6-chat` - 更强大的模型

**环境变量**:
```env
MINIMAX_API_KEY=eyJhbGci...
MINIMAX_GROUP_ID=1234567890
MINIMAX_API_BASE=https://api.minimax.chat/v1
MINIMAX_MODEL=abab5.5-chat
```

### 其他服务商（预留）

添加新的服务商时，在 `llm_tokens.env` 中按照以下格式：

```env
# {服务商名称}
{SERVICE}_API_KEY=your_api_key
{SERVICE}_API_BASE=https://api.example.com/v1
{SERVICE}_MODEL=default-model-name
```

## Agent 中使用配置

### Python 代码示例

```python
import os

# Kimi
kimi_api_key = os.getenv("KIMI_API_KEY")
kimi_base_url = os.getenv("KIMI_API_BASE", "https://api.moonshot.cn/v1")
kimi_model = os.getenv("KIMI_MODEL", "moonshot-v1-8k")

# MiniMax
minimax_api_key = os.getenv("MINIMAX_API_KEY")
minimax_group_id = os.getenv("MINIMAX_GROUP_ID")
minimax_base_url = os.getenv("MINIMAX_API_BASE", "https://api.minimax.chat/v1")
minimax_model = os.getenv("MINIMAX_MODEL", "abab5.5-chat")
```

### 使用 OpenAI SDK 调用 Kimi

```python
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("KIMI_API_KEY"),
    base_url=os.getenv("KIMI_API_BASE")
)

response = client.chat.completions.create(
    model=os.getenv("KIMI_MODEL"),
    messages=[
        {"role": "user", "content": "你好"}
    ]
)
```

### 使用 MiniMax SDK

```python
import requests

url = f"{os.getenv('MINIMAX_API_BASE')}/text/chatcompletion_v2"
headers = {
    "Authorization": f"Bearer {os.getenv('MINIMAX_API_KEY')}",
    "Content-Type": "application/json"
}
data = {
    "model": os.getenv("MINIMAX_MODEL"),
    "messages": [
        {"sender_type": "USER", "text": "你好"}
    ]
}

response = requests.post(url, headers=headers, json=data)
```

## 安全注意事项

### 权限管理

```bash
# 目录权限
chmod 700 /brain/secrets/system
chmod 700 /brain/secrets/system/agents

# 配置文件权限（敏感）
chmod 600 /brain/secrets/system/agents/llm_tokens.env

# 文档权限（可读）
chmod 644 /brain/secrets/system/agents/SETUP_GUIDE.md
chmod 644 /brain/secrets/system/agents/llm_tokens.env.example
```

### Git 管理

**提交到 git**:
- ✅ `SETUP_GUIDE.md`
- ✅ `llm_tokens.env.example`

**不提交到 git**:
- ❌ `llm_tokens.env`（已在 `.gitignore` 中）

### API Key 轮换

定期轮换 API keys：

1. 在服务商平台生成新的 API key
2. 更新 `llm_tokens.env` 文件
3. 重新加载配置
4. 在服务商平台撤销旧的 API key

```bash
# 更新配置
vim /brain/secrets/system/agents/llm_tokens.env

# 重新加载
/brain/infrastructure/launch/loader_env_vars.py --reload

# 重启使用该配置的 agents
/brain/infrastructure/service/agent-ctl/bin/agentctl restart {agent_name} --apply
```

## 故障排查

### 配置未生效

检查加载日志：
```bash
tail -20 /brain/runtime/logs/config_audit.jsonl | jq .
```

### 权限错误

修复权限：
```bash
chmod 600 /brain/secrets/system/agents/llm_tokens.env
```

### API Key 无效

验证 API key 有效性：

**Kimi**:
```bash
curl -X POST https://api.moonshot.cn/v1/chat/completions \
  -H "Authorization: Bearer ${KIMI_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "moonshot-v1-8k",
    "messages": [{"role": "user", "content": "test"}]
  }'
```

**MiniMax**:
```bash
curl -X POST https://api.minimax.chat/v1/text/chatcompletion_v2 \
  -H "Authorization: Bearer ${MINIMAX_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "abab5.5-chat",
    "messages": [{"sender_type": "USER", "text": "test"}]
  }'
```

## 参考文档

- 全局 Secrets 管理: `/brain/secrets/README.md`
- 配置索引: `/brain/secrets/index.yaml`
- 配置管理规范: `/brain/base/spec/policies/config_management.yaml`
