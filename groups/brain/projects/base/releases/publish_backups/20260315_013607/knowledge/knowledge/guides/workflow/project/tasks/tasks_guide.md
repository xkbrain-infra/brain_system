# Tasks 阶段指南

> 适用于 S6 Tasks 阶段的任务拆分与执行规划作战手册。Owner: **pmo** 主导，**architect** + **qa** 参与。
> 把已通过的 solution/需求，拆成可执行的工程任务（tickets），并把依赖、验收、测试、发布都串起来——从设计走向执行的"Tasking/Planning"阶段。
>
> - Schema: `/brain/base/spec/templates/spec/spec_dsl.yaml#tasks`
> - 流程: `/brain/base/workflow/lifecycle/project.yaml#S6`

---

## 目标（4 件事）

1. **把方案落到任务粒度**: 每个任务可实现、可评审、可测试、可交付
2. **串起关键依赖与关键路径**: 避免"做到一半发现缺依赖/缺权限/缺数据"
3. **把质量与发布前置**: 测试、监控、灰度、回滚不再是最后补
4. **形成可承诺的计划**: 迭代/里程碑、资源、风险与缓冲

---

## 输入（Inputs）

| 来源 | 消费什么 |
|------|----------|
| S5 Solution | 通过的架构设计（模块边界、契约、迁移、发布策略） |
| S2 Requirements | 需求列表（FR+NFR）+ AC（验收标准） |
| S5 Solution | 依赖清单（外部系统、第三方、审批、安全合规） |
| S5 Solution | 测试策略（分层测试、P0 E2E、契约测试计划） |
| S5 Solution | 发布/回滚策略（feature flag、灰度、切流方案） |

---

## 产出（Deliverables）

### A. Work Breakdown Structure（WBS）/ Ticket 列表

按域拆分（建议固定分桶）：

- Frontend / Mobile
- Backend / API
- Data / Pipeline
- AI / Model（如有）
- Infra / SRE
- Security / Compliance
- QA / Automation
- Docs / Runbook / Release Notes

### B. 依赖图 + 关键路径

- 哪些 ticket 依赖哪些 ticket
- 哪些是 blocker（卡住就无法集成/测试/上线）

### C. 里程碑计划（Milestones）

典型里程碑：

- **Design freeze**（设计冻结）
- **Dev complete**（开发完成）
- **Test complete**（测试完成）
- **Release ready**（上线就绪）
- **GA**（正式发布）+ Retro

### D. 可追溯性（Traceability）

需求/AC → 任务 → 测试用例 → 缺陷 → 发布版本

---

## 任务怎么拆（Task Decomposition）

### 4.1 从"用户旅程/关键流程"倒推

先列出 P0 旅程（E2E）与关键流程（含异常/回滚），再拆任务：

UI/交互 → API → 服务逻辑 → 数据 → 事件 → 观测 → 测试 → 发布

### 4.2 按"契约优先"拆

在多团队/多服务情况下，先拆契约与集成约束任务，否则后期联调爆炸：

- API schema 定稿 + mock/stub
- Event schema 定稿 + consumer/provider contract tests
- 错误码/鉴权/幂等/限流策略

### 4.3 把 NFR 变成"工程任务"，不要停留在文档

每个 NFR 至少落到 1-3 个具体 tasks：

- **性能**: 索引/缓存/批处理/压测脚本/基线
- **可靠性**: 重试/幂等/补偿/熔断/降级
- **安全**: RBAC、审计日志、敏感数据处理、扫描与修复
- **可观测性**: 指标/日志字段/trace、dashboard、告警

### 4.4 把"发布与回滚"拆成显式 tasks（强制）

- feature flag 接入与默认策略
- 灰度扩量逻辑与阈值
- 回滚步骤与演练（至少 dry-run）
- 数据迁移：双写/回填/切流/回退脚本

---

## 质量门槛（DoR / DoD）

### Definition of Ready（DoR）：票能开工的标准

- 目标清楚、范围明确
- 输入输出定义清楚（接口/数据/依赖）
- 验收标准可测（AC）
- 风险/依赖已标注（blocker 有 owner）
- 估时可给出（哪怕粗估）

### Definition of Done（DoD）：票算完成的标准

**强烈建议写进每个 ticket：**

- 代码合入 + 评审通过
- 单测/静态检查通过
- 对应的 API/契约测试更新（如适用）
- 监控/日志/trace 打点完成（如适用）
- 文档/Runbook 更新（如适用）
- QA 验收条件满足（含回归影响说明）

---

## 全栈项目的"任务分桶模板"

下面是一个典型 P0 需求拆任务的样子（按每条需求套）：

```markdown
## 需求：P0 - 用户完成 X 流程（含异常）

### Frontend
- FE-1：页面/组件实现 + 表单校验
- FE-2：错误态/加载态/空态
- FE-3：埋点（事件A/B/C）+ 关键指标上报

### Backend
- BE-1：API 定义 & schema（含错误码）
- BE-2：鉴权/RBAC & 审计日志
- BE-3：核心业务逻辑（含幂等/重试语义）
- BE-4：集成依赖（第三方/内部服务）+ mock

### Data
- DA-1：表结构/索引/迁移脚本
- DA-2：数据对账口径 + 质量规则
- DA-3：回填/双写/切流方案（如需要）

### Infra/SRE
- OP-1：配置/feature flag
- OP-2：dashboard + 告警
- OP-3：灰度/回滚 runbook + 演练

### QA/Automation
- QA-1：API 自动化用例（P0）
- QA-2：契约测试（consumer/provider）
- QA-3：E2E（仅核心旅程）
- QA-4：性能基线/压测脚本（如 NFR 要求）
```

---

## 排期与关键路径

在任务阶段强制标注三类标签：

- **Blocker**: 不完成就无法联调/测试
- **Critical Path**: 影响里程碑日期
- **Risk-heavy**: 需要 POC/Spike 或早做

常见关键路径（全栈）：

```
契约定稿 → mock 可用 → 联调环境就绪 → 冒烟 → 功能测试 → 回归 → 灰度
```

---

## 看板泳道建议

把任务看板分成两条泳道：

- **Product Deliverables**（功能交付）
- **Quality & Release Deliverables**（质量与发布交付）

规定：**每个 P0 功能 ticket 必须配至少 1 个 Quality/Release ticket**（契约/监控/自动化/回滚/压测），否则 verification 会被迫背锅。

---

## 三个执行阶段

### Phase 1: 规划（architect + pmo 共同完成）

1. **architect 拆任务**: 基于 05_solution.yaml 的模块列表，按分桶模板拆成原子任务
2. **pmo 制定执行计划**: 分批、关键路径、并行轨道、里程碑
3. **三方讨论 team_allocation**: 需要多少 dev agent、多少 qa agent

### Phase 2: 分配与执行（pmo 主导）

1. pmo 通过 agentctl 创建 dev/qa agent
2. 从 backlog 取任务分配给 agent
3. 持续监控进度，动态调节

### Phase 3: Review 闭环（qa 主导）

1. dev 完成任务 → 提交到 review/
2. qa review → pass 进 done/ / fail 退回修改
3. 所有任务 done → 进入 S7

---

## 目录结构

```
spec/06_tasks/
  plan.yaml              # 任务总览（WBS、依赖图、里程碑、team_allocation）
  backlog.yaml           # 未分配任务池
  assigned/              # 每个 agent 的任务清单
    dev1.yaml
    dev2.yaml
    qa1.yaml
  review/                # 待 review 的任务
    T-003.yaml
  done/                  # review 通过的任务
    T-001.yaml
  task_manager.yaml      # 调度器配置
```

---

## plan.yaml 内容

```yaml
# spec/06_tasks/plan.yaml
dod_global: "所有任务 review pass + S7 验收通过"

milestones:
  - name: "Design freeze"
    condition: "所有契约定稿 + mock 可用"
  - name: "Dev complete"
    condition: "所有开发任务 done"
  - name: "Test complete"
    condition: "S7 验收通过"
  - name: "Release ready"
    condition: "灰度/回滚演练完成"
  - name: "GA"
    condition: "正式发布 + Retro"

team_allocation:
  discussion: "architect + pmo 共同决定"
  dev_count: 3
  qa_count: 1
  rationale: "5 个模块，3 个可并行，预估 2 周完成"

execution_plan:
  phases:
    - batch: 1
      tasks: [T-001, T-002, T-003]
      description: "核心模块，无依赖，可并行"
    - batch: 2
      tasks: [T-004, T-005]
      description: "依赖 batch 1 产出"
  critical_path: [T-001, T-004, T-006]
  parallel_tracks:
    - [T-001, T-002, T-003]
    - [T-004, T-005]

dependency_graph:
  T-004: [T-001, T-002]  # T-004 依赖 T-001 和 T-002
  T-005: [T-003]
  T-006: [T-004, T-005]

swimlanes:
  product: "功能交付 tickets"
  quality_release: "质量与发布 tickets（契约/监控/自动化/回滚/压测）"
  rule: "每个 P0 功能 ticket 必须配至少 1 个 quality_release ticket"
```

---

## backlog.yaml 内容

```yaml
# spec/06_tasks/backlog.yaml
tasks:
  - id: T-001
    title: "实现 IPC 消息路由模块"
    bucket: Backend
    priority: P0
    tags: [critical_path]
    maps_to_module: M-001
    maps_to_requirement: R-001
    deps: []
    dor: "API schema 定稿 + mock 可用"
    dod: "单元测试通过 + API 测试通过 + code review pass"
    ac: "消息路由延迟 P95 < 50ms，错误率 < 0.1%"
    estimated_effort: "3d"
    status: pending

  - id: T-002
    title: "实现 agent 生命周期管理"
    bucket: Backend
    priority: P0
    tags: [blocker]
    maps_to_module: M-002
    maps_to_requirement: R-002
    deps: []
    dor: "agentctl CLI 可用"
    dod: "agentctl 集成测试通过 + review pass"
    ac: "create/start/stop/purge 全流程 E2E 通过"
    estimated_effort: "2d"
    status: pending
```

---

## task_manager.yaml 核心

```yaml
# spec/06_tasks/task_manager.yaml
project_binding: "{project_id}"

state_machine:
  states: [pending, assigned, in_progress, blocked, review, revision, done]
  transitions:
    pending → assigned: "pmo 分配"
    assigned → in_progress: "agent 开始工作"
    in_progress → blocked: "agent 遇到阻塞"
    blocked → in_progress: "阻塞解除"
    in_progress → review: "agent 完成，提交 review"
    review → done: "qa review pass"
    review → revision: "qa review fail"
    revision → review: "修改后重新提交"

timer:
  check_interval_seconds: 300
  rules:
    - condition: "agent 超过 2h 未更新进度"
      action: "ping agent 询问状态"
    - condition: "blocked 超过 4h"
      action: "升级给 architect"
    - condition: "review/ 有新任务"
      action: "通知 qa"
    - condition: "某 agent 完成当前任务"
      action: "从 backlog 分配下一个"

ipc_events:
  TASK_ASSIGNED: "pmo → agent"
  TASK_PROGRESS: "agent → pmo"
  TASK_COMPLETED: "agent → pmo → review/"
  TASK_BLOCKED: "agent → pmo"
  TASK_REVIEW_RESULT: "qa → pmo"
  TASK_AVAILABLE: "pmo → idle agent"
```

---

## 任务流转

```
backlog (pending)
    ↓ pmo 分配
assigned/{agent}.yaml (assigned)
    ↓ agent 开始
assigned/{agent}.yaml (in_progress)
    ↓ agent 完成          ↓ agent 卡住
review/{task}.yaml      assigned/{agent}.yaml (blocked)
    ↓ qa review              ↓ 阻塞解除
    ├→ pass → done/{task}.yaml
    └→ fail → assigned/{agent}.yaml (revision) → review/
```

---

## pmo 调度规则

1. **优先分配**: P0 > P1 > P2，同优先级按依赖拓扑排序
2. **依赖检查**: deps 中所有任务 done 才能分配
3. **空闲检测**: agent 完成当前任务 → 立即从 backlog 取下一个
4. **阻塞升级**: blocked 超阈值 → 通知 architect → 必要时重新分配
5. **Review 驱动**: dev 提交 → 自动通知 qa → qa review → 结果回写

---

## 完成标准（Exit Criteria）

- [ ] **P0 需求已拆到可执行 tickets**（含测试与发布 tasks）
- [ ] **依赖项有 owner/日期/备选方案**
- [ ] **关键路径明确**，blocker 已前置
- [ ] **每个 P0 ticket 有 DoR/DoD/AC**
- [ ] **QA 具备用例设计输入**（契约、环境、数据、可观测性）
- [ ] **release/rollback tasks 已进入计划**（不是"上线前再说"）
- [ ] plan.yaml 写完（WBS、依赖图、里程碑、team_allocation）
- [ ] backlog.yaml 所有任务已入池
- [ ] task_manager.yaml 已配置（状态机、timer、IPC 事件）
- [ ] dev/qa agent 已创建（agentctl list 确认）

---

## 常见反模式

| 反模式 | 修正 |
|--------|------|
| 任务粒度太大（"实现整个后端"） | 拆到单个模块/接口级别，一个 agent 可独立完成 |
| 没有 deps 导致并行冲突 | 必须声明依赖，pmo 按拓扑排序分配 |
| DoD 写"做完" | 必须有具体验收标准（测试通过 + review pass） |
| NFR 只停留在文档 | 每个 NFR 至少落到 1-3 个具体 tasks |
| 发布/回滚最后补 | 必须在 tasks 阶段就拆成显式 ticket |
| 功能 ticket 没配质量 ticket | 每个 P0 功能 ticket 必须配至少 1 个 Quality/Release ticket |
| pmo 不跟进 | timer 定期 ping，不能等 agent 主动汇报 |
| review 堆积 | qa 收到通知后优先处理 review，不能让 dev 等太久 |
| 所有任务一次性分配 | 按批次分配，前一批完成后再分下一批 |
| 契约没先定就开工 | 先拆契约任务（API/event schema + mock），否则联调爆炸 |
