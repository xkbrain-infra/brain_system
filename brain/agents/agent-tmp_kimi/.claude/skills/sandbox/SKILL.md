---
id: G-SKILL-SANDBOX
name: sandbox
description: "当需要创建、启动、停止、管理 sandbox 容器时使用。用于项目级开发、测试、预发布、审计环境的容器化管理。"
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Edit, Bash, Agent
argument-hint: "[create|start|stop|destroy|list|exec|validate] [project] [type] [options...]"
metadata:
  status: active
  source_project: /xkagent_infra/groups/brain/projects/base/sandbox
  publish_target: /xkagent_infra/brain/base/skill/sandbox
  spec_ref: /xkagent_infra/brain/base/sandbox/index.yaml
  gates_ref: /xkagent_infra/brain/base/sandbox/gates.yaml
---

# sandbox

<!-- L1 -->
## 触发场景

| 情境 | 跳转 |
|------|------|
| 为项目创建新的 sandbox 环境 | → [创建 Sandbox](#创建-sandbox) |
| 启动已存在的 sandbox | → [启动 Sandbox](#启动-sandbox) |
| 停止运行中的 sandbox | → [停止 Sandbox](#停止-sandbox) |
| 查看项目所有 sandbox | → [列出 Sandbox](#列出-sandbox) |
| 进入 sandbox 执行命令 | → [执行命令](#执行命令) |
| 验证 sandbox 配置合规 | → [验证配置](#验证配置) |
| 销毁 sandbox | → [销毁 Sandbox](#销毁-sandbox) |

**约束：** 所有操作必须通过本 skill，禁止直接 docker 命令操作 sandbox 容器。

---

```bash
# 服务脚本（黑盒调用，禁止读取源码或模板文件）
SANDBOX_SERVICE="python3 /xkagent_infra/groups/brain/projects/base/sandbox/service/sandbox_service.py"
```

> **⚠️ 重要**: sandbox_service.py 是黑盒 CLI 工具，内部实现（compose 模板、Dockerfile、providers）由脚本自行处理。
> **禁止**读取 `sandbox_service.py`、`compose.base.yaml`、`Dockerfile.base` 等实现文件。直接调用脚本即可。

<!-- L2 -->
## 创建 Sandbox

```bash
# 创建开发环境 sandbox
/sandbox create <project_name> --type development

# 创建测试环境 sandbox（自动运行测试后销毁）
/sandbox create <project_name> --type testing

# 创建预发布环境
/sandbox create <project_name> --type staging

# 创建审计环境（完全隔离）
/sandbox create <project_name> --type audit
```

**流程：**
1. 验证项目存在且配置有效
2. 生成 instance_id
3. 应用项目级配置覆盖（.sandbox/config.yaml）
4. 通过 LEP Gates 检查
5. 创建容器并注册到 registry

### Workflow Bootstrap 用法

当你是在执行 `BOOTSTRAP_DISPATCH`，而不是普通开箱测试时，创建 sandbox 后还必须补齐 runtime 面：

```bash
# 1. 创建 sandbox
/sandbox create <project_name> --type development

# 2. 在 sandbox 内补 runtime 目录
/sandbox exec <project_name> --instance <instance_id> --command '
  mkdir -p /workspace/runtime/agents \
           /workspace/runtime/config/agentctl \
           /workspace/runtime/tasks \
           /workspace/runtime/template_bundles/agents
  if [ ! -f /workspace/runtime/config/agentctl/agents_registry.yaml ]; then
    cat > /workspace/runtime/config/agentctl/agents_registry.yaml <<EOF
version: "1.0"
updated: "bootstrap"
projects: {}
EOF
  fi
'
```

判定 `BOOTSTRAP_COMPLETE` 前必须确认：
- `docker inspect` / health check 为 `healthy`
- `/workspace/runtime/agents` 存在
- `/workspace/runtime/config/agentctl/agents_registry.yaml` 存在
- 未在 host `/xkagent_infra/brain/agents` 创建任何 project-scoped agent

---

## 启动 Sandbox

```bash
# 启动指定 sandbox
/sandbox start <project_name> --instance <instance_id>

# 启动所有开发环境 sandbox
/sandbox start <project_name> --type development
```

---

## 停止 Sandbox

```bash
# 停止指定 sandbox
/sandbox stop <project_name> --instance <instance_id>

# 停止并清理（测试环境默认清理）
/sandbox stop <project_name> --instance <instance_id> --cleanup
```

---

## 列出 Sandbox

```bash
# 查看项目所有 sandbox
/sandbox list <project_name>

# 查看指定类型的 sandbox
/sandbox list <project_name> --type development

# 查看所有运行中的 sandbox
/sandbox list --active
```

---

## 执行命令

```bash
# 在 sandbox 中执行命令
/sandbox exec <project_name> --instance <instance_id> --command "<cmd>"

# 进入 sandbox shell
/sandbox exec <project_name> --instance <instance_id> --shell
```

---

## 验证配置

```bash
# 验证项目 sandbox 配置
/sandbox validate <project_name>

# 验证是否符合 LEP Gates
/sandbox validate <project_name> --check-gates
```

---

## 销毁 Sandbox

```bash
# 销毁指定 sandbox（归档数据后删除）
/sandbox destroy <project_name> --instance <instance_id>

# 强制销毁（不归档）
/sandbox destroy <project_name> --instance <instance_id> --force
```

---

<!-- L3 -->
## 部署类型特性

| 类型 | 代码 | 特性 | 网络隔离 |
|------|------|------|----------|
| development | DEV | 热重载、调试工具、RW挂载 | bridge |
| testing | TST | 测试运行器、覆盖率报告、自动清理 | bridge |
| staging | STG | 生产级配置、冒烟测试 | custom_bridge |
| audit | AUD | 审计工具、不可变、全日志 | isolated |

---

## 命名规范

容器名称格式：`{group}-{project}-{type}-{instance_id}`

示例：`brain-dashboard-dev-a7f3k2`

---

## 项目级扩展

项目可通过 `.sandbox/config.yaml` 覆盖基础配置：

```yaml
sandbox:
  environment:
    MY_VAR: value
  ports:
    - "${HOST_PORT_REDIS}:6379"
  volumes:
    - ${PROJECT_ROOT}/data:/workspace/data/custom
```

详细规则参见：`/xkagent_infra/groups/brain/projects/base/sandbox/PROJECT_EXTENSION.md`
