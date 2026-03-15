# Retrospective 阶段指南

> 适用于 S8 Retrospective 阶段的复盘作战手册。Owner: **orchestrator** 主导，pmo/architect 参与。
> 目标不是总结，而是**改进系统**。
>
> - 流程: `/brain/base/workflow/lifecycle/project.yaml#S8`

---

## 定位

把本次交付暴露的流程/质量/协作问题，转成**可验证的行动项**（有 owner、有截止、有度量），并进入下一轮计划与门禁。

适用范围：

- 每次 release / sprint 结束
- 重大 incident / 线上回滚之后（可单独做 incident postmortem）

---

## 输入（Inputs）

为了避免"凭感觉复盘"，至少准备这些数据：

### A. 交付与节奏

- 计划 vs 实际：里程碑偏差、范围变更次数、返工次数
- cycle time / lead time（从需求进入到上线）
- 关键路径变动（哪里卡住）

### B. 质量与缺陷

- 缺陷分布：按严重级别（S0-S3）、模块、发现阶段（dev/QA/UAT/prod）
- 缺陷逃逸率（escape rate）：上线后发现的缺陷占比
- 回归成本：回归轮次、平均修复时长、重开率（reopen）

### C. Verification & 发布

- 测试通过率趋势、失败主要原因（环境、数据、用例脆弱、依赖不稳）
- 灰度期间指标变化、回滚触发与否
- 监控告警：有效告警 vs 噪音告警

### D. 运行与事件（如果有）

- incident 时间线、影响范围、MTTR、根因分类（代码/配置/依赖/流程）

> 这些数据决定复盘讨论的"事实基础"，防止变成吐槽会。

---

## 复盘覆盖面（5 维模型）

### 1. Scope & Decision（范围与决策）

- 需求是否可测？AC/NFR 是否清晰？
- 是否出现 scope creep？为什么？
- 关键决策是否太晚（导致返工）？

### 2. Build & Integration（构建与集成）

- 集成问题集中在哪里（契约不清/字段漂移/环境差异）？
- 依赖管理是否可靠（版本、变更通知、SLA）？

### 3. Verification（QA/测试）

- 缺陷主要在哪个阶段暴露？为何没更早发现？
- 自动化覆盖是否合理（unit/API/E2E 的比例是否失衡）？
- 环境/数据是否成了瓶颈？

### 4. Release & Operability（发布与可运维）

- 灰度、回滚、开关策略是否可控？
- 监控是否能"提前发现问题"？告警是否可行动？
- runbook、值班升级是否顺畅？

### 5. Team & Process（协作与流程）

- 交接是否清晰（Dev ↔ QA ↔ PM ↔ SRE）？
- triage 是否高效（定级一致、修复 SLA 达成）？
- 文档/决策记录是否可追溯？

---

## 怎么开 retrospective（60-90 分钟）

### Step 0：设定基调（5 min）

- 事实导向、聚焦系统改进、不追责个人
- 时间盒：讨论不超过范围

### Step 1：回顾事实（10-15 min）

展示 1 页数据：

- 计划 vs 实际
- 缺陷分布 + 逃逸率
- MTTR/回滚情况（如有）
- 最大 3 个瓶颈点

### Step 2：收集观察（10-15 min）

用固定结构收集，避免情绪化：

- **Keep**: 做得好、要保持
- **Problem**: 痛点/阻塞
- **Idea**: 改进想法

（也可用 Start/Stop/Continue）

### Step 3：找根因（15-25 min）

对 Top 3 问题做根因分析：

- 5 Whys 或 Fishbone
- 重点找"系统性原因"（门禁缺失、输入不清、依赖不稳、自动化欠债）

### Step 4：产出行动项（15-20 min）

每个行动项必须满足 **SMART + 可验证**：

| 字段 | 说明 |
|------|------|
| Action | 做什么（具体可执行） |
| Owner | 谁负责 |
| Due | 截止日期 |
| Metric | 用什么指标证明有效 |
| Follow-up | 何时复查（下次 retro/每周质量会） |

**经验规则**：宁可 3 条真的做完，也不要 20 条写在墙上。

### Step 5：关闭（5 min）

- 确认行动项进入 backlog/看板
- 明确下次检查点

---

## 产出（Deliverables）

### 1. Retro Summary（1 页）

- 本次目标/范围
- 数据摘要
- Top 3 收获/问题

### 2. Root Cause Notes

- 每个 Top 问题的根因链条（不要只写表象）

### 3. Action Items Backlog（带门禁）

- 行动项列表（owner、due、metric）

### 4. Process/Quality Rule Updates

- 哪些规则要升级：例如新增门禁、更新 DoR/DoD、更新测试策略

---

## 全栈项目最有价值的行动项方向

优先做这些，立竿见影：

### A. 需求可测性门禁（DoR）

- P0 需求必须有 AC（Given/When/Then）
- NFR 必须量化（P95、可用性、错误率）
- 没有就不能进入开发/测试

### B. 契约测试与版本治理

- API/schema 变更必须：版本策略 + 向后兼容检查
- consumer-driven contract tests 接入 CI

### C. 环境与数据稳定性工程

- 测试环境健康检查自动化
- 测试数据种子化/可重复生成
- 环境漂移（config drift）检测

### D. 自动化分层优化

- 增加 API 回归覆盖，减少脆弱 E2E
- 把历史 bug hotspot 变成回归套件

### E. 发布与可观测性门禁

- 仪表盘/告警/traceId 必须齐全才可上线
- 回滚演练变成 release 前必做项

---

## 复盘的退出标准（Retro Exit Criteria）

- [ ] 行动项 ≤ 5 条，全部有 owner/due/metric
- [ ] 至少 1 条行动项是"门禁/自动化/制度"层面的（不是喊口号）
- [ ] 行动项进入看板并设定复查时间
- [ ] 下次 retro 会检查上次行动项完成率与效果指标

---

## 模板

### Retro Summary（1 页模板）

```markdown
# Retro: {project_id} / {release}

## 基本信息
- **Release/Sprint**:
- **目标与范围**:
- **时间**: 计划 vs 实际

## 关键数据
- 计划 vs 实际偏差:
- Defect 分布: S0=, S1=, S2=, S3=
- Escape rate:
- MTTR（如有）:

## Keep（≤ 3）
1.
2.
3.

## Problems（Top 3）
1.
2.
3.

## Root Causes（对应 Top 3）
1.
2.
3.

## Actions（≤ 5）

| Action | Owner | Due | Success Metric | Status |
|--------|-------|-----|----------------|--------|
| | | | | |

## Rule Updates（新增/修改门禁）
-
```

### Action Item 模板

```markdown
| Action | Owner | Due | Success Metric | Status |
|--------|-------|-----|----------------|--------|
| 增加 API 契约测试覆盖 P0 接口 | qa | 2026-03-15 | P0 接口契约覆盖率 100% | pending |
| P0 需求必须有 AC 才能进入开发 | pmo | 2026-03-01 | DoR 门禁拦截率 | pending |
```
