---
id: G-SKILL-PROJECT_DELIVERY
name: project_delivery
description: "当任务涉及启动项目、项目规划、执行项目、发布项目、审计项目、task 建模、checklist 更新，或项目生命周期操作时使用。"
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Edit, Bash, Agent, Skill, mcp__mcp-brain_ipc_c__ipc_send, mcp__mcp-brain_ipc_c__ipc_recv, mcp__mcp-brain_ipc_c__ipc_search
argument-hint: "[intake|research|bootstrap|planning|task-modeling|execution|release|audit|status|checklist] [project_id]"
metadata:
  status: active
  source_project: /xkagent_infra/groups/brain/projects/base
  publish_target: /xkagent_infra/brain/base/skill/project_delivery
  spec_ref: /brain/base/workflow/project_delivery/index.yaml
---

# project_delivery

<!-- L1 -->
## 触发场景

| 情境 | 跳转 |
|------|------|
| 新项目启动 | → [新项目入口](#新项目入口) |
| 已有项目，进入某个阶段 | → [阶段路由](#阶段路由) |
| 查看项目状态 / checklist | → [状态查询](#状态查询) |
| 不确定当前在哪个阶段 | → 先执行 `status <project_id>` |

---

<!-- L2 -->
## 新项目入口

```bash
# 完整启动（intake + bootstrap）
/project_delivery intake <group_id> "<goal>"
# 输出: project_id, project_root

# 快速初始化
/project_delivery init <group_id> <project_name>
```

> 深入规则：读取 `spec_ref/intake.yaml`

---

## 阶段路由

9-Stage 主流程：

```
intake → research → bootstrap → planning → task-modeling → execution → release → audit → feedback
```

<!-- L2 -->
| 阶段 | 命令 | 关键输出 | 深入规则 |
|------|------|----------|----------|
| intake | `intake <group_id> <goal>` | `intake_record` | `spec_ref/intake.yaml` |
| research | `research <project_id>` | `research_report` | `spec_ref/research.yaml` |
| bootstrap | `bootstrap <project_id>` | `bootstrap_verification_report` | `spec_ref/bootstrap.yaml` |
| planning | `planning <project_id>` | `project_plan` | `spec_ref/planning.yaml` |
| task-modeling | `task-modeling <project_id>` | `task_graph` | `spec_ref/task_modeling.yaml` |
| execution | `execution <project_id>` | `task_event_history` | `spec_ref/execution.yaml` |
| release | `release <project_id>` | `release_report` | `spec_ref/release.yaml` |
| audit | `audit <project_id>` | `audit_report` | `spec_ref/audit.yaml` |

---

## 状态查询

```bash
/project_delivery status <project_id>     # 当前阶段 + task graph
/project_delivery checklist <project_id>  # checklist 完成度
/project_delivery tasks <project_id>      # READY set
```

---

<!-- L3 -->
## 核心规则（执行阶段加载）

进入具体阶段时按需读取：

> Checklist 机制：`/brain/base/workflow/project_delivery/SPEC_CHECKLIST.yaml`
> Task 建模规范：`/brain/base/workflow/project_delivery/contracts/state_machines.yaml`
> Execution 合约：`/brain/base/workflow/project_delivery/contracts/execution_contract.yaml`
> Release 合约：`/brain/base/workflow/project_delivery/contracts/release_contract.yaml`

**三条硬规则：**
- Checklist item 不可静默跳过，必须显式 waive 或记录 blocked
- Evidence 必须有可追溯路径（artifact_refs），不能只写"已完成"
- Blocker 必须显式记录 `blocked_by` + `eta`

---

## Spec 引用

| 场景 | 读取路径 | 读取时机 |
|------|----------|----------|
| 各阶段详细规则 | `spec_ref/<stage>.yaml` | 进入该阶段时 |
| Checklist 基线（72项） | `spec_ref/SPEC_CHECKLIST.yaml` | task-modeling 阶段 |
| 状态机定义 | `spec_ref/contracts/state_machines.yaml` | execution 阶段 |
| IPC 协作模式 | `/brain/base/spec/policies/ipc/` | 需要通知 PMO 时 |

`spec_ref` = `/brain/base/workflow/project_delivery`
