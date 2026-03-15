# Research 阶段指南

> 适用于 S3 Research 阶段的调研作战手册。Owner: **researcher**，architect 协助。
> 明确怎么做、做哪些、查什么资料、怎么把调研结果转成需求条目。
>
> - Schema: `/brain/base/spec/templates/spec/spec_dsl.yaml#research`
> - 流程: `/brain/base/workflow/lifecycle/project.yaml#S3`

---

## 目标

把"我觉得应该这样做"变成**有依据的判断**，并直接转化为需求条目和验收标准。

---

## 6 类调研

在需求阶段，research 分 6 类。不一定全做，但要明确选哪几类、为什么。

| # | 类型 | 对应 PRD 的 |
|---|------|------------|
| A | 用户/场景调研 | 目标、场景、痛点 |
| B | 需求/价值验证 | 价值假设、指标树、MVP |
| C | 竞品/替代方案 | 方案取舍、基线功能 |
| D | 技术可行性/依赖 | 排期依赖、技术风险 |
| E | 非功能需求（NFR） | 验收标准 |
| F | 行业/政策/标准 | 风险与合规 |

---

## A. 用户/场景调研

**目的**: 补足"你以为的需求"与"真实用户行为"之间的鸿沟。

### 联网查什么

- **用户讨论/抱怨/求助**: 论坛、社区、Reddit、知乎、GitHub Issues
- **产品评价**: App Store/Google Play 评论、G2/Capterra（B2B）
- **现有流程/教程**: YouTube/B站教程、产品使用指南、FAQ（看用户在哪一步卡住）

### 输出

- Top 用户任务（Use Cases）
- Top 痛点（频次 × 影响）
- 真实术语表（用户怎么说，而不是你怎么说）

---

## B. 需求/价值验证

**目的**: 把"想做"变成"值得做"，并能写出 KPI/ROI/成功指标。

### 联网查什么

- **市场规模与趋势**: 行业报告摘要、分析机构公开数据
- **客户为什么买/不买**: 公开 case study、竞品白皮书、客户证言
- **JTBD**: 用户真正"雇佣"产品来完成什么任务

### 输出

- 价值假设（Value Hypothesis）
- 指标树（North Star → 输入指标）
- MVP 的"最小价值闭环"

---

## C. 竞品/替代方案调研

**目的**: 避免闭门造车，找到"差异化切口"和"必须对齐的行业 baseline"。

### 必查资料

- **竞品官网文档**: 功能页、pricing、FAQ、changelog（非常关键）
- **竞品开发者文档/API**: 边界、限制、默认值、权限模型
- **竞品体验走查**: 注册 → 关键任务 → 导出/分享 → 失败路径

### 输出

- "任务级"对比表（Competitor × Task）
- 机会点：更快 / 更稳 / 更省 / 更自动 / 更可控
- 基线功能清单（table stakes vs differentiators）

---

## D. 技术可行性/依赖调研

**目的**: 让需求"可实现、可排期"，并提前识别关键依赖/风险。

### 必查资料

- **依赖的外部系统/SDK/API 文档**: 限流、配额、鉴权、数据字段、兼容性
- **类似功能的开源/行业实现**: 架构文章、RFC、GitHub Issues（看坑在哪里）
- **性能/成本基线**: 云厂商定价页、容量规划案例

### 输出

- 关键约束（Constraints）：延迟、吞吐、成本上限
- 依赖列表（Dependency Matrix）：owner、SLA、风险、备选方案
- 技术风险 Top 5（含缓解/预案）

---

## E. 非功能需求（NFR）调研

**目的**: 把"要快、要稳、要安全"写成可测量的需求与验收标准。

### 必查资料

- **行业对标**: 同类产品的 SLA、延迟指标、数据保留策略、权限/审计能力
- **安全合规**: OAuth/SSO、日志审计、数据加密、PII 处理
- **可观测性**: 监控指标、告警阈值、追踪与日志标准

### 质量模型检查表（ISO/IEC 25010）

| 特性 | 要量化什么 |
|------|-----------|
| 性能 | P95/P99 延迟、QPS、吞吐量 |
| 可靠性 | 可用性 SLA、RPO/RTO |
| 安全 | 认证方式、权限模型、加密标准 |
| 可用性 | 关键任务完成率、出错率 |
| 可维护性 | 部署频率、回滚时间 |
| 可观测性 | 日志覆盖率、告警覆盖率 |

### 输出

- NFR 清单（按质量模型）
- 每项 NFR 的量化指标
- 上线门禁（Go/No-Go 条件）

---

## F. 行业/政策/标准调研

**目的**: 确认"红线"和"必备要求"，避免后期返工。

### 必查资料

- 监管/行业标准官方网站（隐私、金融、医疗等）
- 大客户安全问卷常见项（SOC2/ISO27001 等）
- 政府/权威机构的研究与指南

### 输出

- 合规需求条目（直接进 PRD/NFR）
- 风险与审批流（DPIA/法务/安全评审等）

---

## 执行流程

### Step 0: 写 Research Brief（1 页）

开始调研前必须先写清楚：

```markdown
## Research Brief
- 研究目标：要回答哪些问题（不超过 5 个）
- 目标用户/市场范围
- 假设列表：你现在相信什么
- 决策点：研究结果将影响什么决定（MVP、路线、指标、排期）
```

### Step 1: 联网搜索（必须使用 WebSearch）

**这是强制步骤**，必须使用 WebSearch 工具做实际联网搜索，禁止仅凭已有知识编写结论。

#### 搜索输入来源

从 `01_alignment.yaml` 和 `02_requirements.yaml` 提取：
- S1 的 goal、in_scope、constraints → 生成技术可行性搜索词
- S2 的 must-have 需求 → 生成竞品功能对比搜索词
- S2 的 NFR → 生成性能/安全基线搜索词

#### 搜索维度（至少覆盖 2 个）

1. **竞品/替代方案**: 搜索同类产品、开源替代、功能对比
2. **技术可行性**: 搜索依赖库/API/框架的文档、限制、已知问题
3. **用户场景**: 搜索真实用户反馈、痛点、使用模式
4. **NFR 基线**: 搜索同类产品的性能指标、SLA、安全标准
5. **行业标准**: 搜索相关法规、合规要求（如适用）

#### 搜索结果处理

- **每个有价值的来源，单独写一个 `references/SR-{序号}_{标题}.md` 文件**
- 用 WebFetch 深入阅读后，把关键内容摘录到该文件中
- 搜索完成后，从各 references 文件中提取结论写入 `spec/03_research.yaml`

#### 单个来源文件格式

文件名示例：`references/SR-001_crewai_docs.md`

```markdown
# CrewAI Documentation

- **来源**: [CrewAI Official Docs](https://docs.crewai.com/)
- **时间**: 2026-02-22
- **搜索维度**: competitive
- **搜索词**: "agent orchestration framework comparison 2026"
- **关联**: S1 goal「构建 agent 编排系统」→ S2 must「R1 多 agent 协作」

---

## 关键内容

CrewAI 是一个多 agent 编排框架，核心概念：

- **Agent**: 有角色、目标、工具的自主单元
- **Task**: 分配给 agent 的具体任务，有预期输出
- **Crew**: 一组 agent + task 的编排单元，支持顺序/并行

### 架构特点

- 角色分工明确，每个 agent 有独立 system prompt
- 支持 tool use（函数调用）
- 内置 memory（短期 + 长期）
- **不支持动态 agent 创建**（启动时固定）

### 限制

- Agent 数量启动时固定，不能运行时增减
- 不支持跨 Crew 通信
- Memory 只在单次 run 内有效（长期 memory 需额外配置）

### 与我们项目的关联

- 角色分工模式可参考，但我们需要动态创建 agent
- Tool use 机制类似我们的 MCP
- 不支持 IPC，我们的 IPC 方案是差异化优势

## 原文摘录

> "CrewAI enables AI agents to assume roles, share goals,
> and operate in a cohesive unit - much like a well-oiled crew."
> — CrewAI Docs, Introduction

> "Each agent can have its own set of tools, and the crew
> can be configured to run tasks sequentially or in parallel."
> — CrewAI Docs, Core Concepts
```

输出：竞品任务对比表、技术可行性评估、用户语料主题、风险/依赖假设

### Step 2: 收敛可行方向

基于 Step 1 的搜索结果，归纳出 **至少 2 个主流可行方向**：

- 每个方向包含：名称、大致方案、优缺点、可行性评估
- 明确推荐进入 S4 详细对比的 2-3 个方向
- 不可行的方向也要记录，说明排除原因

### Step 3: 收敛为需求资产

- 需求列表（FR + NFR）+ AC（验收标准）
- MVP 切分与优先级（MoSCoW / RICE）
- Decision Log：哪些点定了、依据是什么、谁拍板

---

## 检索式模板

把 `[方括号]` 替换成你的产品/竞品/领域：

### 用户痛点语料

```
"[产品/领域] 很难用" "卡住" "bug" "无法" site:zhihu.com
"[竞品名] review" "pricing" "limitations"
"[任务] best tool" "alternative" "vs"
```

### 竞品功能/边界/限制

```
"[竞品名] documentation" OR "help center" OR "API" OR "rate limit"
"[竞品名] changelog" OR "release notes" OR "roadmap"
"[竞品名] SSO" OR "RBAC" OR "audit log" OR "data retention"
```

### NFR/性能对标

```
"[领域] SLA" "uptime" "status page"
"[竞品名] status page" / "[竞品名] incident"
"[领域] P95 latency benchmark"
```

### 行业标准/合规

```
"[行业] compliance requirements" "data privacy" "PII"
"[国家/地区] + [行业] + regulation + data"
```

---

## 最终交付物

调研完成后，必须落盘这 7 份资产（放在 `references/` 或直接写入 `spec/03_research.yaml`）：

1. **Research Brief** — 目标 / 问题 / 假设 / 决策点
2. **来源文件** (`references/SR-{序号}_{标题}.md`) — 每个来源一个文件，含原文链接、摘要、关键内容
3. **竞品任务对比表** — Competitor × Task：步骤、缺口、亮点
4. **Viable Directions** — 至少 2 个主流可行方向（方案轮廓 + 优缺点 + 可行性）
5. **Recommended Shortlist** — 推荐进入 S4 详细对比的 2-3 个方向
6. **风险/依赖矩阵** — owner、日期、备选方案
7. **需求清单补充** — 调研中新发现的 FR + NFR

> 原始资料（文档、截图、链接）放 `references/`，
> `spec/03_research.yaml` 只写结论和引用。

---

## 完成标准

- [ ] Research Brief 已写（目标、问题、假设、决策点）
- [ ] **实际使用了 WebSearch 做联网搜索**（有搜索记录为证）
- [ ] 至少完成 A-D 中的 2 类调研
- [ ] 竞品对比至少覆盖 2 个替代方案
- [ ] findings 每条有 sources（URL）和 confidence（高/中/低）
- [ ] **至少找出 2 个主流可行方向**，有大致方案轮廓
- [ ] 推荐 2-3 个方向进入 S4 详细对比
- [ ] 技术风险 Top N 已识别，有缓解措施
- [ ] 原始资料已归档到 `references/`
