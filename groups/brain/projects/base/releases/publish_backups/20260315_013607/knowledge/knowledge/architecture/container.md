# Agent Brain 容器

## 基本信息

| 项目 | 值 |
|------|-----|
| 容器名 | `agent-brain` |
| 镜像基础 | `ubuntu:24.04` |
| 工作目录 | `/app` |
| 进程管理 | supervisord |
| 时区 | `Asia/Shanghai` |

## 关键路径（容器内）

```
/app/agent_workspace/     # compose.yaml, Dockerfile, supervisord.conf 所在目录
/app/agent_workspace/compose.yaml   # Docker Compose 定义
/app/agent_workspace/Dockerfile     # 镜像构建
/app/agent_workspace/supervisord.conf  # 进程管理配置
/brain/                   # bind mount: ../agent_brain
/app/groups/              # bind mount: ../groups
/app/memory/              # bind mount: ./docker-data/memory
/root/                    # bind mount: ./docker-data/root (持久化 home)
```

## Supervisor 托管服务

| 服务 | 命令 | 说明 |
|------|------|------|
| sshd | `/usr/sbin/sshd -D` | SSH 访问 (端口 22→宿主 8422) |
| brain_ipc | `brain_ipc` (C binary) | IPC daemon, unix socket |
| agent_orchestrator | `python3 bin/brain-agentctl serve` | Agent 生命周期管理 |

## Volume Mounts

```yaml
# 核心挂载
- .:/app/agent_workspace          # 源码 + 配置
- ../agent_brain:/brain           # Brain 规范
- ../groups:/app/groups           # 所有 group 的 app 目录
- ./docker-data/root:/root        # 持久化 home（SSH key, zsh history 等）
- ./docker-data/memory:/app/memory

# NAS 挂载（xkquant 专用）
- /xnas-workspace/projects/xkquant_workbench:/app/groups/xkquant/xkquant_workbench
- /xnas-workspace/projects/xkquant/xkquant_resources:/app/groups/xkquant/xkquant_resources

# 其他
- /var/run/docker.sock:/var/run/docker.sock  # Docker-in-Docker
```

## 预装工具

- **AI CLI**: claude-code, gemini-cli, codex
- **开发**: python3 + venv, nodejs 20, git, docker, build-essential
- **包管理**: uv (Python), npm (Node)
- **Shell**: zsh + oh-my-zsh, tmux
- **搜索**: ripgrep, fd-find
- **编辑器**: vim

## 宿主机目录结构

```
{project_root}/
├── agent_workspace/    # → /app/agent_workspace
├── agent_brain/        # → /brain
├── groups/             # → /app/groups
│   ├── brain_system/
│   ├── xkquant/
│   ├── digital_resources/
│   ├── local_model_lab/
│   ├── userspace/
│   └── commerce/
```

## 常用操作

```bash
# 宿主机上重建容器
cd {project_root}/agent_workspace
docker compose up -d --build

# 宿主机上进入容器
docker exec -it agent-brain zsh

# 容器内查看服务状态
supervisorctl status
```
