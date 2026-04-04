---
id: G-SKILL-SANDBOX
name: sandbox
description: "当需要创建、启动、停止、管理 sandbox 容器时使用。用于项目级开发、测试、预发布、审计环境的容器化管理。"
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Edit, Bash, Agent
argument-hint: "始终执行: /xkagent_infra/brain/bin/sandboxctl [create|start|stop|destroy|list|exec|validate] ..."
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
# 统一黑盒入口（禁止直接引用 groups 下实现路径）
SANDBOX_SERVICE="/xkagent_infra/brain/bin/sandboxctl"
```

> **⚠️ 重要**: sandbox 只能通过 `/xkagent_infra/brain/bin/sandboxctl` 调用。
> 内部实现由 `/xkagent_infra/brain/infrastructure/service/brain_sandbox_service/` 提供；`sandbox_service.py`、compose 模板、Dockerfile、providers 全部视为黑盒。
> **禁止**在命令里直接引用 `brain_sandbox_service/current/sandbox_service.py`、旧的 `groups/.../sandbox/service/sandbox_service.py`、`compose.base.yaml`、`Dockerfile.base` 等实现文件。
> 这样可以保持 LEP scope 正常生效，同时给 agent 提供稳定入口。

## 使用规则

1. 先加载本 skill，再执行 sandbox 操作。
2. 永远不要在 Bash 里发明 `/sandbox ...` 伪命令。
3. 真正执行时，必须使用：

```bash
$SANDBOX_SERVICE <subcommand> ...
```

4. 允许的子命令只有：`create` `start` `stop` `list` `exec` `validate` `destroy` `spawn-agent`
5. 禁止的做法：
   - 直接运行 `docker ...`
   - 直接运行 `python3 /xkagent_infra/brain/infrastructure/service/brain_sandbox_service/current/sandbox_service.py ...`
   - 直接运行旧兼容路径 `python3 /xkagent_infra/groups/brain/projects/base/sandbox/service/sandbox_service.py ...`
   - 直接读取或修改 sandbox 模板、provider、compose 实现文件

## 角色边界

- `manager` 在 orchestrator workflow 中只负责生成 `BOOTSTRAP_DISPATCH`，不得直接执行 `sandboxctl create|start|stop|destroy|exec`
- `manager` 如需查看状态，只允许使用 `sandboxctl list` / `sandboxctl validate`
- `devops` 是 sandbox lifecycle/bootstrap 的唯一执行者，负责真正调用 `sandboxctl create --with-agent orchestrator ...`
- 如果你是 `manager`，不要把“我已经知道该用什么命令”误当成“我可以自己执行这个命令”

## 命令模板

```bash
# host 上的 sandbox lifecycle / bootstrap 统一走 published wrapper
$SANDBOX_SERVICE create <project_name> --type <development|testing|staging|audit> [--with-agent orchestrator] [--pending-id <pending_id>] [--model <provider/model>]
$SANDBOX_SERVICE start <project_name> --instance <instance_id>
$SANDBOX_SERVICE stop <project_name> --instance <instance_id>
$SANDBOX_SERVICE list <project_name>
$SANDBOX_SERVICE exec <project_name> --instance <instance_id> --command "<cmd>"
$SANDBOX_SERVICE validate <project_name>
$SANDBOX_SERVICE destroy <project_name> --instance <instance_id> --force
$SANDBOX_SERVICE spawn-agent <project_name> --instance <instance_id> --role <designer|dev|qa|researcher|devops|architect> [--slot <NN>] [--model <provider/model>]
```

```bash
# sandbox 容器内部 spawn project agents 时，走 sandbox-local service bundle
/xkagent_infra/runtime/sandbox/_services/service/brain_sandbox_service/bin/brain_sandbox_service \
  spawn-agent <project_name> \
  --instance <instance_id> \
  --role <designer|dev|qa|researcher|devops|architect> \
  [--slot <NN>] \
  [--model <provider/model>]
```

```bash
# sandbox 容器内部如需直接做 agentctl smoke / lifecycle 验证，使用 sandbox-local bridge
export AGENTCTL_CONFIG_DIR=/xkagent_infra/runtime/sandbox/<instance_id>/config/agentctl

agentctl --config-dir "$AGENTCTL_CONFIG_DIR" add <agent_id> \
  --group brain \
  --role <developer|qa|researcher|architect|devops|step_validator> \
  --agent-type <provider> \
  --model <model_name> \
  --scope project \
  --project <project_id> \
  --sandbox-id <instance_id> \
  --desired-state stopped \
  --apply
agentctl --config-dir "$AGENTCTL_CONFIG_DIR" start <agent_id> --apply
agentctl --config-dir "$AGENTCTL_CONFIG_DIR" stop <agent_id> --apply
agentctl --config-dir "$AGENTCTL_CONFIG_DIR" purge <agent_id> --apply --force
```

<!-- L1.5 -->
## 路径架构

> ⚠️ **关键说明**：Brain 系统运行在嵌套 Docker 环境，host 路径与容器内路径不同。

| 用途 | 容器内路径 | Host 路径 |
|------|-----------|-----------|
| Brain 核心（只读） | `/brain` | `/services/xkagent_infra/brain` |
| Groups 项目（可写） | `/groups` | `/services/xkagent_infra/groups` |
| Sandbox Runtime（隔离） | `/xkagent_infra/runtime/sandbox/{instance_id}` | `/services/xkagent_infra/runtime/sandbox/{instance_id}` |
| Services（只读） | `/xkagent_infra/runtime/sandbox/_services` | （来自镜像） |

**挂载关系**：
```
/brain      → /services/xkagent_infra/brain              (ro)
/groups     → /services/xkagent_infra/groups             (rw)
/tmp        → /tmp                                      (rw)
/xkagent_infra/runtime/sandbox/{instance_id} → /services/xkagent_infra/runtime/sandbox/{instance_id}  (rw)
```

**容器内有效路径**：
- `/brain/base/spec/` - Brain 规范
- `/brain/agents/` - Agent 配置
- `/groups/brain/projects/<project>/` - 项目代码（可写）
- `/xkagent_infra/runtime/sandbox/{instance_id}/agents/` - Sandbox 实例 agent
- `/xkagent_infra/runtime/sandbox/{instance_id}/config/` - Sandbox 实例配置
- `/xkagent_infra/runtime/sandbox/{instance_id}/.bootstrap/instance.yaml` - Sandbox 实例状态文件
- `/xkagent_infra/runtime/sandbox/_services/` - Sandbox 服务（来自镜像）

<!-- L2 -->
## 创建 Sandbox

```bash
# 创建开发环境 sandbox
$SANDBOX_SERVICE create <project_name> --type development

# 创建 sandbox 并同时完成 project orchestrator bootstrap
$SANDBOX_SERVICE create <project_name> --type development --with-agent orchestrator --pending-id <pending_id>

# 创建 sandbox，并显式指定 orchestrator 使用的 provider/model
$SANDBOX_SERVICE create <project_name> --type development --with-agent orchestrator --pending-id <pending_id> --model minimax/minimax-m2.7

# 创建测试环境 sandbox（自动运行测试后销毁）
$SANDBOX_SERVICE create <project_name> --type testing

# 创建预发布环境
$SANDBOX_SERVICE create <project_name> --type staging

# 创建审计环境（完全隔离）
$SANDBOX_SERVICE create <project_name> --type audit
```

**流程：**
1. 验证项目存在且配置有效
2. 生成 instance_id
3. 应用项目级配置覆盖（.sandbox/config.yaml）
4. 通过 LEP Gates 检查
5. 创建容器并注册到 registry
6. 如果指定 `--with-agent orchestrator`，额外执行：
   - 等容器 healthy
   - 物化 `/xkagent_infra/runtime/sandbox/<instance_id>/agents/<agent_name>/`
   - 写 sandbox-local `agents_registry.yaml`
   - 启动 host/container 双侧 IPC bridge（`/tmp/brain_ipc.sock`、`/tmp/brain_ipc_notify.sock`）
   - 预写 Claude bootstrap/trust 状态
   - 调用 `agentctl start`
   - 验证 tmux session、`.brain/agent_runtime.json` 和本地 `/tmp/brain_ipc.sock` ping

### Workflow Bootstrap 用法

当你是在执行 `BOOTSTRAP_DISPATCH`，不要再手工补 runtime。统一调用黑盒：

```bash
$SANDBOX_SERVICE create <project_name> \
  --type development \
  --with-agent orchestrator \
  --pending-id <pending_id> \
  [--model <provider/model>]
```

职责边界：
- `manager`：生成上面的参数，发送 `BOOTSTRAP_DISPATCH` 给 `agent-brain_devops`，然后等待结果
- `devops`：真正执行上面的 `sandboxctl create --with-agent orchestrator ...`

判定 `BOOTSTRAP_COMPLETE` 前必须确认：
- `docker inspect` / health check 为 `healthy`
- `/xkagent_infra/runtime/sandbox/<instance_id>/agents/<agent_name>` 存在
- `/xkagent_infra/runtime/sandbox/<instance_id>/config/agentctl/agents_registry.yaml` 存在
- `.brain/agent_runtime.json` 已生成
- sandbox 内 `tmux has-session -t <agent_name>` 成功
- sandbox 内 `/tmp/brain_ipc.sock` 可连通，且 `{"action":"ping"}` 返回 `{"status":"ok"...}`
- 如果 project agent 使用 Claude Code CLI，必须预写 `/root/.claude.json` 的 `projects[{runtime cwd}]` trust/onboarding 状态；不得把 theme / `Yes, I trust this folder` prompt 留给人工首登
- `/groups/brain/projects/<project_name>/src` 存在且可读（验证 groups mount 工作）

### 项目路径

项目直接在 `/groups/brain/projects/<project_name>/`，不需要 `/workspace/project` 中间层。

**注意**：项目修改在容器内 `/groups/` 下进行，会直接反映到 host。

---

## 启动 Sandbox

```bash
# 启动指定 sandbox
$SANDBOX_SERVICE start <project_name> --instance <instance_id>

# 启动所有开发环境 sandbox
$SANDBOX_SERVICE start <project_name> --type development
```

---

## 停止 Sandbox

```bash
# 停止指定 sandbox
$SANDBOX_SERVICE stop <project_name> --instance <instance_id>

# 停止并清理（测试环境默认清理）
$SANDBOX_SERVICE stop <project_name> --instance <instance_id> --cleanup
```

---

## 列出 Sandbox

```bash
# 查看项目所有 sandbox
$SANDBOX_SERVICE list <project_name>

# 查看指定类型的 sandbox
$SANDBOX_SERVICE list <project_name> --type development

# 查看所有运行中的 sandbox
$SANDBOX_SERVICE list --active
```

---

## 执行命令

```bash
# 在 sandbox 中执行命令
$SANDBOX_SERVICE exec <project_name> --instance <instance_id> --command "<cmd>"

# 进入 sandbox shell
$SANDBOX_SERVICE exec <project_name> --instance <instance_id> --shell
```

---

## 验证配置

```bash
# 验证项目 sandbox 配置
$SANDBOX_SERVICE validate <project_name>

# 验证是否符合 LEP Gates
$SANDBOX_SERVICE validate <project_name> --check-gates
```

---

## 销毁 Sandbox

```bash
# 销毁指定 sandbox（归档数据后删除）
$SANDBOX_SERVICE destroy <project_name> --instance <instance_id>

# 强制销毁（不归档）
$SANDBOX_SERVICE destroy <project_name> --instance <instance_id> --force
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
```

详细规则参见：`/xkagent_infra/groups/brain/projects/base/sandbox/PROJECT_EXTENSION.md`
