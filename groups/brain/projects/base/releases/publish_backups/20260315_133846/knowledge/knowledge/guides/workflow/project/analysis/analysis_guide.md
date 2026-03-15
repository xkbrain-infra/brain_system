# Analysis & Decision 阶段指南

> 适用于 S4 Analysis & Decision 阶段的决策作战手册。Owner: **architect** 主持，全员参与讨论，**PMO** 最终审批。
>
> - Schema: `/brain/base/spec/templates/spec/spec_dsl.yaml#analysis`
> - 流程: `/brain/base/workflow/lifecycle/project.yaml#S4`

---

## 目标

把需求与调研结论，转成**可执行的选择**（做/不做、怎么做、先做什么），并把取舍、风险、指标、成本写清楚，形成**可追责的决策记录**。

典型要拍板的决策：

- Problem/Goal 是否成立（值得做吗？）
- Scope/MVP（边界、第一版交付什么）
- Option/Approach（方案 A vs B vs C）
- 资源与排期承诺（能 commit 吗）
- 上线门槛与风险策略（灰度、回滚、合规）
- 成功指标与验收口径（怎么判定成功/失败）

---

## 输入（Inputs）

从上游阶段接入的资产（有则最好，没有就补齐最低限度）：

- **S3 Research 输出**: 用户任务/痛点、竞品对比、viable_directions、recommended_shortlist
- **S2 Requirements**: 目标、范围、需求列表、AC、NFR、依赖
- **S1 Alignment**: 约束（人力容量、预算、平台限制、合规要求、时间窗口）
- **现状数据**: 基线指标（baseline），比如当前转化/时延/成本/人工耗时
- **风险与开放问题清单**: 哪些点没定、会影响方案选择

---

## 怎么做（Activities）

### A. 建立决策题目清单（Decision Backlog）

把需要拍板的点写成可回答的问题（每条都有 owner 和截止时间）：

- "MVP 是否包含 X？"
- "鉴权用 OAuth 还是自研？"
- "我们是做集成式还是插件式？"
- "是否支持多租户？第一版支持到什么程度？"

**经验规则**：如果不拍板会导致返工/延期/风险暴露，就必须进入决策清单。

---

### B. 选项分析（Options Analysis）

对每个关键决策点，至少给出 **2 个可行选项**（包括"不做/延后"），然后用统一维度比较。

#### 比较维度（够用且通用）

| 维度 | 评估什么 |
|------|----------|
| 价值/收益 | 对 KPI 的贡献、用户覆盖面 |
| 成本 | 研发/运维/支持成本、长期复杂度 |
| 风险 | 技术风险、合规风险、进度风险、依赖风险 |
| 时间 | lead time、关键路径影响 |
| 质量/NFR | 性能、可靠性、安全、可观测性 |
| 可逆性 | 做错了能不能回滚/替换（reversibility） |

**必须写清为什么不选其他方案**（否则评审时会被打回）。

---

### C. 量化与取舍（Trade-off & Prioritization）

把"拍脑袋"变成"可解释的取舍"：

- **价值量化**: 预期提升多少？影响多少用户？节省多少成本？
- **成本估算**: 粗到 30% 也行，但要说明假设（人周、云成本、依赖交付）
- **优先级方法**:
  - 功能优先级：P0/P1/P2 或 MoSCoW
  - 项目优先级：RICE（Reach / Impact / Confidence / Effort）

输出物：**MVP 列表 + 延后列表 + 取舍理由**

---

### D. 风险策略（Risk Strategy）与门禁（Gates）

把风险从"列表"变成"策略"：

- **风险 Top 5**: 概率 × 影响
- 每条风险至少给一个：**缓解（Mitigation）+ 预案（Contingency）**
- 定义**上线门禁（Go/No-Go）**：
  - 性能：P95 < X
  - 稳定性：error rate < Y
  - 安全：通过某项审计/扫描
  - 观测：核心指标/告警齐全
- **发布策略**: 灰度比例、回滚条件、演练计划

---

### E. 决策会议与"记录即承诺"

会议的目标不是讨论爽，而是**输出决议**：

- 谁是 DRI/Approver（最终拍板人）
- 争议如何裁决（时间盒 + 决策规则）
- 形成 **Decision Log / ADR**（Architecture Decision Record）

---

## 产出（Deliverables）

一个成熟的 analysis_and_decision 阶段，产出这些可执行资产：

### 1. Decision Brief（1-2 页）

目标、范围、关键决策点、推荐方案、取舍、风险、里程碑。

### 2. Options Matrix（方案对比表）

选项 A/B/C 在价值/成本/风险/时间/NFR/可逆性上的对比。

### 3. MVP & Release Plan

v0/MVP/v1/v2 清单（含 out-of-scope）。

### 4. NFR & Acceptance Criteria

可测量的性能/稳定性/安全/观测指标。

### 5. Dependency & RACI/DRI

依赖项 owner、交付时间、备用方案。

### 6. Decision Log / ADR

可追溯、可复盘（避免"换人就失忆"）。

---

## 模板

### Options Matrix（方案对比表）

```markdown
| 维度 | 选项 A | 选项 B | 选项 C |
|------|--------|--------|--------|
| 价值（KPI 贡献） | | | |
| 覆盖用户/场景 | | | |
| 研发成本（人周） | | | |
| 运维/长期复杂度 | | | |
| 风险（技术/合规/进度） | | | |
| NFR（性能/安全/可靠性） | | | |
| 可逆性（回滚/替换难度） | | | |
| 结论 | / | / | / |
```

### ADR（决策记录）最小结构

```markdown
## ADR-{序号}: {决策标题}

- **Decision**: 决定采用 X
- **Context**: 背景与约束
- **Options**: A / B / C
- **Why**: 选择理由（含数据/假设）
- **Consequences**: 后果与影响面
- **Revisit**: 复盘触发条件/日期
```

### Decision Backlog 条目

```yaml
- id: D-001
  question: "鉴权用 OAuth 还是自研 token？"
  owner: architect
  deadline: "2026-02-25"
  status: open          # open / decided / deferred
  decision: ""
  rationale: ""
  alternatives_rejected: ""
```

---

## 完成标准（Exit Criteria）

- [ ] 目标/KPI 与 baseline 已明确（知道要改善什么、改善多少）
- [ ] MVP 范围锁定（in/out scope 明确），并与关键干系人对齐
- [ ] 关键决策点全部有结论（或明确"推迟到何时由谁决定"）
- [ ] 方案对比与取舍理由写清（为什么选它，不选什么）
- [ ] NFR 与验收标准可测试、可监控
- [ ] Top 风险有缓解与预案，上线门禁（Go/No-Go）定义完毕
- [ ] 依赖与责任人明确（RACI/DRI），里程碑可承诺（commit）
- [ ] 决策记录落地（Decision Log/ADR）并可被检索

---

## 常见反模式

| 反模式 | 修正 |
|--------|------|
| 只写推荐方案，不写为什么不选其他 | 必须写替代方案及排除理由，否则评审被打回 |
| 风险只列不策略 | 每条风险必须有缓解 + 预案，否则等于没管 |
| "全做"代替优先级 | 强制区分 MVP / v1 / v2，全做 = 没排期 |
| 决策没有 owner | 每个决策点必须有 DRI，否则没人负责 |
| 会议讨论完没有记录 | 记录即承诺，没有 Decision Log 的会议 = 白开 |
| 成本估算"待定" | 粗估也行（±30%），但不能空着 |
