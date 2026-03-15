# Brain Docker Infrastructure

Brain 组 Docker 基础设施项目，提供基于 Ubuntu 24.04 的全栈 AI Agent 运行环境。

## 项目结构

```
brain-docker/
├── Dockerfile          # 镜像构建定义
├── compose.yaml        # Docker Compose 配置
├── .env                # 环境变量（自动加载，需与 compose.yaml 同级）
├── configs/            # 配置文件目录
│   ├── .env.example    # 环境变量示例（最小配置）
│   ├── .env.full.example  # 环境变量示例（完整配置）
│   ├── requirements.lock.txt  # Python 依赖
│   ├── sshd_config     # SSH 服务配置
│   └── supervisord.conf    # Supervisor 进程管理配置
├── scripts/            # 构建和运维脚本
├── services/           # 服务组件
├── spec/               # 项目规范文档
└── README.md           # 本文件
```

## 三域架构

本项目遵循 Brain 三域架构模式：

| 域 | 路径 | 用途 |
|----|------|------|
| **Source** | `/xkagent_infra/groups/brain/platform/docker/` | 源码开发 |
| **Runtime** | `/xkagent_infra/app/brain/docker/` | 运行时数据 |
| **Published** | `/xkagent_infra/brain/platform/docker/` | 发布态（含 compose、配置、脚本）|

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
cd /xkagent_infra/groups/brain/platform/docker
bash scripts/build.sh
```

### 运行

```bash
cd /xkagent_infra/app/brain/docker
bash /xkagent_infra/groups/brain/platform/docker/scripts/start.sh
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

## 依赖

- Docker 24.0+
- Docker Compose 2.0+

## 更多信息

- 文档: https://github.com/xkbrain-infra/brain_system

---

**Owner**: brain
**Created**: 2026-03-15
**Version**: 1.0.0
