---
id: G-SKILL-DOCKER
name: docker
description: "在隔离的 Docker 容器中执行命令，用于需要沙箱环境、避免污染宿主机的任务：依赖安装、编译、测试、脚本执行。"
user-invocable: true
disable-model-invocation: false
allowed-tools: Bash
argument-hint: "[run] --image <image> --project <path> --cmd <command>"
metadata:
  status: active
  source_project: /xkagent_infra/brain/base/skill/docker
  version: "1.0.0"
---

# docker — 容器沙箱执行

在独立容器中执行命令，项目目录通过 volume mount 注入。容器退出后不留残留。

## 何时使用

- 运行不确定的脚本（避免影响宿主机环境）
- 需要特定语言版本或依赖（如 python:3.11、node:20）
- 编译、测试、lint（隔离副作用）
- 不要用于：需要持久化服务、需要 GPU、需要访问 IPC socket

## 使用方式

```python
from brain.base.skill.docker.src.client import run_in_sandbox

result = run_in_sandbox(
    image="python:3.11-slim",
    project_root="/xkagent_infra/groups/brain/projects/my_project",
    command="pip install -r requirements.txt && pytest tests/"
)
print(result.stdout)
print(result.returncode)
```

或直接用 Bash：

```bash
docker run --rm \
  -v /xkagent_infra/groups/brain/projects/my_project:/workspace \
  -w /workspace \
  python:3.11-slim \
  bash -c "pip install -r requirements.txt && pytest tests/"
```

## 常用镜像

| 场景 | 镜像 |
|------|------|
| Python 任务 | `python:3.11-slim` |
| Node/前端 | `node:20-alpine` |
| 通用 shell | `alpine:latest` |
| 编译 C++ | `gcc:13` |

## 注意

- 容器内默认无网络访问（如需要，加 `--network host`，但要谨慎）
- 大依赖安装建议先 pull 镜像，避免超时
- project_root 内的文件修改**会反映到宿主机**（volume mount 是双向的）
