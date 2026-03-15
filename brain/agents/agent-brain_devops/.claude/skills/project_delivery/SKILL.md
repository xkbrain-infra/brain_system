---
id: G-SKILL-PROJECT_DELIVERY
name: project_delivery
description: "This skill should be used when the user asks to \"启动项目\", \"创建项目\", \"项目交付\", \"项目规划\", \"执行项目\", \"发布项目\", \"审计项目\", \"项目进展\", \"task建模\", \"checklist更新\", or mentions project lifecycle operations (intake/research/planning/execution/release/audit)."
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Edit, Bash, Agent, Skill, mcp__mcp-brain_ipc_c__ipc_send, mcp__mcp-brain_ipc_c__ipc_recv, mcp__mcp-brain_ipc_c__ipc_search
argument-hint: "[intake|research|planning|task-modeling|execution|release|audit|checklist|status] [project_id] [options]"
---

# Project Delivery — 项目交付 Workflow

**路径**: `/brain/base/workflow/project-delivery`

Brain 标准项目交付流程，覆盖从需求进入到审计反馈的完整闭环。

## 9-Stage 主流程

```
intake → research → bootstrap → planning → task-modeling → execution → release → audit → feedback
```

| 阶段 | 职责 | 关键输出 |
|------|------|----------|
| **intake** | 项目受理、立项最小条件检查 | `intake_record`, `project_root` |
| **research** | 技术调研、约束识别、方案选型 | `research_report`, `risk_list` |
| **bootstrap** | 环境准备、sandbox启动、基线确认 | `bootstrap_verification_report` |
| **planning** | 交付目标、架构设计、里程碑规划 | `project_plan`, `milestones` |
| **task-modeling** | deliverables → task graph 建模 | `task_graph`, `owner_assignment` |
| **execution** | 任务派发、执行、review、test | `task_event_history`, `evidence_bundle` |
| **release** | 构建汇总、stage gate、生产发布 | `release_report`, `approval_chain` |
| **audit** | 执行审计、根因分析、改进识别 | `audit_report`, `findings` |
| **feedback** | 改进闭环、归档、经验沉淀 | `closure_record`, `archive_ref` |

## 参数解析

`/project_delivery $ARGUMENTS`:

### 阶段操作
- `intake <group_id> <goal>` → 创建新项目 intake
- `research <project_id>` → 执行项目调研
- `bootstrap <project_id>` → 准备 sandbox 环境
- `planning <project_id>` → 制定项目计划
- `task-modeling <project_id>` → task graph 建模
- `execution <project_id>` → 进入执行阶段
- `release <project_id>` → 执行发布流程
- `audit <project_id>` → 执行审计

### 查询与状态
- `status <project_id>` → 查询项目状态与 checklist 完成度
- `checklist <project_id>` → 查看/更新 SPEC_CHECKLIST 实例
- `tasks <project_id>` → 查看 task graph 与 READY set

### 快捷操作
- `init <group_id> <project_name>` → 快速初始化新项目（intake + bootstrap）
- `plan <project_id>` → 快捷规划（research + planning）

## SPEC_CHECKLIST 核心机制

workflow 要求项目维护一份 `spec_checklist` 实例，解决"workflow 写了但执行是否逐条做到不透明"的问题。

### Checklist 结构

```yaml
spec_checklist:
  project_id: "PROJ-001"
  base_items: 72                    # workflow 标准基线项
  completed: 45                     # 已完成
  blocked: 3                        # 阻塞中
  waived: 2                         # 显式放弃
  missing_evidence: 5               # 缺证据

  by_stage:
    intake: { total: 6, done: 6 }
    research: { total: 8, done: 7, blocked: 1 }
    # ...
```

### Severity 定义

| 级别 | 含义 | 缺失后果 |
|------|------|----------|
| **critical** | 关键项 | 直接阻断阶段通过门或完成度声明不可信 |
| **high** | 重要项 | 显著降低交付质量、可验证性或可审计性 |
| **medium** | 一般项 | 不会造成立即阻断，但造成治理或追踪缺口 |

### 基线统计

- **Total**: 72 items
- **Critical**: 34 items
- **High**: 32 items
- **Medium**: 6 items

## 核心规则

### G-PD-001: Checklist 不可静默跳过
```
❌ 错误: "这个 item 不重要，跳过"
✅ 正确: "INT-003 scope 未定义，阻塞 -> 通知 PMO 决策"
```

### G-PD-002: Evidence 必须可追溯
```
❌ 错误: task notes 写 "已完成"
✅ 正确: artifact_refs: ["/path/to/output.yaml"]
```

### G-PD-003: 状态变更必须持久化
```
❌ 错误: 口头通知任务完成
✅ 正确: task_manager EVENT 记录 + checklist 状态更新
```

### G-PD-004: Blocker 必须显式记录
```
❌ 错误: "等依赖好了再继续"
✅ 正确: 记录 blocked_by: "DEP-XXX", eta: "2026-03-15"
```

## Task 建模规则

### Task vs Todo 边界

| | Task | Todo |
|--|------|------|
| **粒度** | 可独立交付的工作单元 | 个人执行的步骤 |
| **owner** | 明确的责任 agent | 个人笔记 |
| **状态机** | 受 workflow 状态约束 | 自由勾选 |
| **追踪** | task_manager 记录 | 不进入系统 |

### Task 字段规范

```yaml
task:
  id: "PROJ-001-T001"
  title: "实现用户认证模块"
  owner: "agent_system_dev1"           # 主责
  participants: ["agent_system_dev2"]  # 参与
  reviewer: "agent_system_architect"   # review 责任人
  depends_on: ["PROJ-001-T003"]        # 前置依赖
  trigger: "manual|auto|event"         # 触发方式
  ready_when: "dependency_done"        # 就绪条件
  blocked_by: ""                       # 阻塞原因
  evidence_required:                   # 必需证据
    - code_review
    - unit_test
```

### READY Set 计算

```
READY = { task | deps_done(task) ∧ ¬blocked(task) ∧ ¬conflict(task) ∧ owner_ready(task) }
```

- **并行度**: 非冲突任务可同时 dispatch
- **冲突检测**: 同资源/同文件任务串行
- **owner_ready**: agent 当前 load < capacity

## 执行流程标准

### Execution Entry (S6)

1. **装载**: approved task graph + checklist baseline
2. **计算 READY set**: 基于依赖和约束
3. **持久化 assignment**: 记录派发意图
4. **dispatch**: IPC 发送任务给 worker
5. **收集 ack**: 确认 worker 接收
6. **更新状态**: task_manager + checklist

### Handoff 规则 (S6-S7)

```
IMPLEMENTED → REVIEW → TEST → QA → DONE
     ↓          ↓       ↓     ↓
   Rework   Rework  Rework  Block
```

- **Review Gate**: code review 必须记录 review_record
- **Test Gate**: 自动化测试必须有 test_results
- **QA Gate**: QA review 必须有 qa_records
- **Rework**: 未通过时回到 IMPLEMENTED，更新 retry_count

### Release Gate (S7)

| Gate | 通过条件 |
|------|----------|
| **Stage Gate** | build_summary ✓, review_summary ✓, test_summary ✓ |
| **Production Gate** | approval_chain ✓, smoke_test ✓, rollback_plan ✓ |

## 关键文档路径

| 文档 | 路径 |
|------|------|
| Workflow Index | `/brain/base/workflow/project-delivery/index.yaml` |
| SPEC_CHECKLIST | `/brain/base/workflow/project-delivery/SPEC_CHECKLIST.yaml` |
| Checklist Template | `/brain/base/workflow/project-delivery/spec_checklist.instance.template.yaml` |
| State Machines | `/brain/base/workflow/project-delivery/contracts/state_machines.yaml` |
| Execution Contract | `/brain/base/workflow/project-delivery/contracts/execution_contract.yaml` |
| Release Contract | `/brain/base/workflow/project-delivery/contracts/release_contract.yaml` |
| Audit Contract | `/brain/base/workflow/project-delivery/contracts/audit_contract.yaml` |

## Workflow 入口文件

| 阶段 | 文件 |
|------|------|
| intake | `/brain/base/workflow/project-delivery/workflow/intake.yaml` |
| research | `/brain/base/workflow/project-delivery/workflow/research.yaml` |
| bootstrap | `/brain/base/workflow/project-delivery/workflow/bootstrap.yaml` |
| planning | `/brain/base/workflow/project-delivery/workflow/planning.yaml` |
| task-modeling | `/brain/base/workflow/project-delivery/workflow/task_modeling.yaml` |
| execution | `/brain/base/workflow/project-delivery/workflow/execution.yaml` |
| release | `/brain/base/workflow/project-delivery/workflow/release.yaml` |
| audit | `/brain/base/workflow/project-delivery/workflow/audit.yaml` |

## IPC 协作模式

### 通知 PMO 场景

```python
# Task 完成
ipc_send(to="agent_system_pmo", message="[PROGRESS] PROJ-001 T001 已完成，进入 REVIEW")

# Blocker 出现
ipc_send(to="agent_system_pmo", message="[BLOCKED] PROJ-001 T003 依赖外部 API 不可用，ETA 未知")

# 需要决策
ipc_send(to="agent_system_pmo", message="[DECISION_NEEDED] PROJ-001 scope 变更申请，详见 /path/to/proposal.md")
```

### Task Manager 注册

```python
# 创建任务
ipc_send(to="service-task_manager", message=json.dumps({
    "event_type": "TASK_CREATE",
    "task_id": "PROJ-001-T001",
    "title": "实现认证模块",
    "owner": "agent_system_dev1"
}))

# 更新状态
ipc_send(to="service-task_manager", message=json.dumps({
    "event_type": "TASK_UPDATE",
    "task_id": "PROJ-001-T001",
    "status": "completed"
}))
```

## 使用示例

### 示例 1: 完整项目启动

```
# 1. Intake
/project_delivery intake org/system "实现用户认证系统"
-> 输出: project_id=SYS-001, project_root=/xkagent_infra/groups/system/projects/auth

# 2. Research
/project_delivery research SYS-001
-> 输出: research_report, risk_list

# 3. Bootstrap
/project_delivery bootstrap SYS-001
-> 输出: sandbox_ready, bootstrap_verification_report

# 4. Planning
/project_delivery planning SYS-001
-> 输出: project_plan, milestones

# 5. Task Modeling
/project_delivery task-modeling SYS-001
-> 输出: task_graph, ready_set=[T001, T002]
```

### 示例 2: 查询 Checklist 完成度

```
/project_delivery checklist SYS-001

输出:
=== SYS-001 Checklist Status ===
Total: 72 | Completed: 45 | Blocked: 3 | Waived: 2

By Stage:
  intake:     6/6  ✓
  research:   7/8  (RES-006 blocked: 推荐路径待定)
  bootstrap:  6/6  ✓
  planning:  10/12 (PLN-009 估算中, PLN-011 里程碑细化中)
  task-modeling: 8/8 ✓
  execution:  8/12 (进行中)

Critical Items Missing Evidence:
  - EXE-003: READY set 未持久化
  - EXE-012: deliverable evidence 不完整
```

### 示例 3: 快速初始化

```
/project_delivery init org/brain "base workflow 优化"
-> 自动执行 intake + bootstrap
-> 输出: project_id=BRN-015, ready for research
```

### 示例 4: Execution 状态查询

```
/project_delivery status BRN-015

输出:
=== BRN-015 Project Status ===
Stage: EXECUTING (S6)
Phase: task_execution

Task Graph:
  READY:     [T003, T004, T005]
  RUNNING:   [T001: agent-bs015-dev1]
  REVIEW:    [T002: waiting for architect]
  DONE:      [T006, T007]
  BLOCKED:   [T008: depends on T001]

Checklist: 38/72 (53%)
Next Gate: EXECUTION_READY_FOR_RELEASE
```

## 发布与生效

该 skill 发布流程:

1. **Source**: `/xkagent_infra/groups/brain/projects/base/skill/project_delivery/`
2. **Publish**: 运行 `/brain/base/scripts/publish_base.sh --publish --domain skill`
3. **Target**: `/brain/base/skill/project_delivery/`
4. **Sync**: 自动同步到所有 agent 的 `.claude/skills/`

生效验证:
```bash
# 检查 skill 是否加载
ls /brain/base/skill/project_delivery/SKILL.md

# 检查 agent 是否同步
ls /xkagent_infra/brain/agents/agent-*/.claude/skills/project_delivery/SKILL.md
```
