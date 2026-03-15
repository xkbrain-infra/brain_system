# Requirements 阶段指南

> 适用于软件/平台/基础设施类项目的 S2 Requirements 填写参考。
>
> - Schema: `/brain/base/spec/templates/spec/spec_dsl.yaml#requirements`
> - 流程: `/brain/base/workflow/lifecycle/project.yaml#S2`

---

## 目标

把"想要什么"变成**可实现、可验收、可排期**的定义，并把关键干系人对齐到：

- 做什么 / 不做什么
- 为什么做（价值与指标）
- 怎么验收（Acceptance Criteria）
- 优先级与取舍

---

## 产出清单

### 1. 需求文档

至少包含：

- 背景 & 问题陈述
- 目标与成功指标（KPI/OKR）
- 用户/角色（Personas）与核心场景（Use Cases）
- 需求列表（Functional Requirements）
- 非功能需求（NFR）：性能、可靠性、可用性、安全、合规、可观测性、成本
- 范围边界（In/Out scope）
- 约束与假设（Constraints / Assumptions）
- 依赖与接口（Dependencies / Integrations）

### 2. 用户故事 + 验收标准

- User Stories: As a… I want… so that…
- Acceptance Criteria: Given / When / Then 或 checklist
- Edge cases / Negative cases（异常路径）

### 3. 优先级与版本切分

- Must / Should / Could / Won't（MoSCoW）或 P0 / P1 / P2
- MVP 定义：最小闭环能力 + 不做清单
- Release plan：v1 / v2 / v3 需求分桶

### 4. 原型与流程（可选但建议）

- 低保真原型 / 流程图 / 状态机
- 关键 API 合约草案

### 5. 风险与开放问题

- Open Questions：待确认点、待拍板点
- 风险：需求不确定、依赖不稳、合规审查、数据质量等

### 6. 评审结论（对齐证据）

- 评审纪要 / Decision Log：哪些点定了、谁拍板、何时复核

---

## 活动清单

### A. 需求获取（Discovery）

- 访谈：用户 / 业务 / 运营 / 支持团队
- 现状分析：流程、系统、数据、痛点
- 竞品 / 对标（如有）

### B. 需求澄清（Clarification）

- 把需求拆成：场景 → 任务 → 步骤 → 输入输出 → 异常
- 定义术语（Glossary），避免"同词不同义"
- 划清边界：哪些由系统负责，哪些由外部负责

### C. 需求细化（Specification）

- 功能需求写到可开发粒度（Epic / Feature / Story）
- NFR 写到可测量：
  - 例：P95 延迟 < 200ms
  - 例：可用性 99.9%
  - 例：日志覆盖率、权限模型

### D. 优先级与取舍（Prioritization）

- 按价值 / 成本 / 风险排序
- 形成 MVP + 后续迭代计划

### E. 对齐评审（Sign-off）

- 需求评审会：工程 / 测试 / 安全 / 运营等
- 明确：验收口径、上线条件、回滚策略

---

## 需求条目模板

每条需求按此格式填写：

```yaml
- id: R1
  text: ""                    # 需求描述
  persona: ""                 # 用户/角色
  scenario: ""                # 核心场景
  value: ""                   # 价值/理由
  priority: P0                # P0/P1/P2
  acceptance_criteria:
    - "Given ... When ... Then ..."
    - "Given ... When ... Then ..."
  edge_cases:
    - ""
  nfr: ""                     # 性能/权限/审计/可用性
  dependencies: ""            # 系统/团队/数据/审批
  monitoring: ""              # 指标、日志、告警
  open_questions: ""          # 待确认点
```

### 填写示例

```yaml
- id: R1
  text: "hooks 拦截 agent 对受保护路径的写入操作"
  persona: "agent（所有角色）"
  scenario: "agent 尝试用 Write/Edit 工具修改 /brain/base/spec/ 下的文件"
  value: "防止 agent 意外或恶意修改核心规范"
  priority: P0
  acceptance_criteria:
    - "Given agent 用 Write 写 /brain/base/spec/test.txt, When pre_tool_use hook 执行, Then 返回 exit code 2 + permissionDecision=deny"
    - "Given agent 用 Write 写 /brain/groups/test.txt, When pre_tool_use hook 执行, Then 正常通过（exit code 0）"
  edge_cases:
    - "agent 使用 Bash echo > 绕过 Write 工具"
    - "文件路径包含 symlink 指向受保护区域"
  nfr: "hook 执行延迟 < 100ms"
  dependencies: "Claude Code 2.1.50+ 支持 permissionDecision 格式"
  monitoring: "audit log 记录每次拦截事件"
  open_questions: "Bash 工具的写操作是否也需要拦截？"
```

---

## NFR 细分参考

| 类别 | 需要量化什么 |
|------|-------------|
| 性能 | P95/P99 延迟、QPS、吞吐量 |
| 可靠性 | 可用性 SLA、故障恢复时间 |
| 安全 | 认证方式、权限模型、数据加密 |
| 合规 | 审计日志、数据保留、隐私要求 |
| 可观测性 | 日志覆盖、指标埋点、告警规则 |
| 成本 | 资源消耗上限、存储增长预算 |
| 兼容性 | 支持的版本范围、向前/向后兼容 |

---

## 完成标准（Exit Criteria）

requirements 阶段结束前，至少满足：

- [ ] 目标 & 指标可量化，且优先级已对齐
- [ ] In/Out scope 明确，MVP 明确
- [ ] 每个核心需求都有 Acceptance Criteria（可测可验）
- [ ] NFR 已覆盖并量化（性能 / 安全 / 可靠性 / 可观测性 / 成本）
- [ ] 关键依赖有 owner + 初步时间窗口
- [ ] Open questions 收敛到可控范围（剩余项有明确决策日期）
- [ ] 评审通过并有决策记录（谁批准 / 谁负责）

---

## 常见反模式

| 反模式 | 修正 |
|--------|------|
| **must-have 写接口名**（`实现 TASK_CREATE`） | 接口是实现，需求是场景。改成 user_story 格式 |
| **user_story 为空** | 没有 user_story = 不知道谁需要这个功能，必须填 |
| **acceptance_criteria 为空** | 没有验收标准 = 无法判断是否完成，必须有 Given/When/Then |
| 需求只写"支持XX功能" | 必须拆到场景 + 验收标准，否则无法验收 |
| NFR 写"性能要好" | 必须量化：P95 < Xms、QPS > Y |
| 没有 edge cases | 异常路径不考虑 = 上线后暴雷，至少列 2 条 |
| 优先级全是 P0 | 全是 P0 = 没有优先级，强制区分 P0/P1/P2 |
| 没有 dependencies | 依赖不明确 = 排期时才发现卡住，提前识别 |
| MVP = 全部需求 | MVP 是最小闭环，不是全部 |

---

## 典型失败案例：BS-026 S2（2026-02-23）

```yaml
# ❌ 错误写法：接口列表，没有场景，没有验收标准
must:
  - id: BS-026-R1
    text: "实现 TASK_CREATE：创建任务，返回 task_id，写入持久化存储"
  - id: BS-026-R2
    text: "实现 TASK_UPDATE：更新任务状态/字段，触发 FSM 状态转换验证"
```

没有 `user_story`，没有 `acceptance_criteria`。architect 收到这份需求只能照旧接口抄，
结果做出来的是一个功能完整但业务场景残缺的服务：
没有项目隔离、没有 PMO 路由、没有任务依赖关系。

```yaml
# ✅ 正确写法：场景驱动，有验收标准
must:
  - id: BS-026-R1
    user_story: "作为 PMO，我需要在创建任务时指定所属项目和组，以便不同项目的任务互不干扰，超期通知也能找到正确的 PMO"
    acceptance_criteria:
      - "Given brain_system PMO 创建任务 When 指定 group_id=brain_system, project_id=BS-026 Then 任务归属 brain_system 项目，xkquant PMO 不会收到此任务的通知"
      - "Given 任务超期 When 调度器扫描 Then task owner 和 spec 对应的 PMO 都收到 TASK_OVERDUE 通知"
    text: "TASK_CREATE 支持 group_id + project_id 项目空间隔离"
```
