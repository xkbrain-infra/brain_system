# XKBrain Infrastructure Docker

基于 Ubuntu 24.04 的全栈 AI Agent 运行环境。

## 包含组件

- **Claude Code** - Anthropic AI 编程助手
- **Gemini CLI** - Google AI CLI
- **Codex CLI** - OpenAI 编程助手
- **Copilot** - GitHub Copilot
- **Brain IPC** - Agent 间通信系统
- **Supervisor** - 进程管理

## 快速开始

### 构建

```bash
cd brain/platform/docker
docker compose build
```

### 运行

```bash
docker compose up -d
```

### 访问

```bash
ssh root@localhost -p 8622
# 密码: aigroup
```

## 配置

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| SSH_PORT | 8622 | SSH 端口 |
| TZ | Asia/Shanghai | 时区 |

## 目录结构

```
brain/
├── infrastructure/    # 服务组件
├── platform/docker/  # Docker 部署
└── base/           # 核心规范
```

## 更多信息

- 文档: https://github.com/xkbrain-infra/brain_system
