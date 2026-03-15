# Verification 阶段指南

> 适用于 S7 Verification 阶段的验收作战手册。Owner: **qa** 主导执行，dev/architect/devops 配合。
>
> - Schema: `/brain/base/spec/templates/spec/spec_dsl.yaml#verification`
> - 流程: `/brain/base/workflow/lifecycle/project.yaml#S7`

---

## 核心目标

1. **验证（Verify）**: 实现是否符合需求与验收标准（AC/NFR）
2. **确认（Validate）**: 是否满足用户场景（UAT/业务验收）
3. **风险控制**: 在上线前把高风险缺陷与不确定性降到可接受水平
4. **发布准备**: 回滚、监控、告警、变更记录、发布窗口都准备好

---

## 输入（Inputs）

测试开始前必须具备，最常见的"测试做不好"的根因是输入不完整。

- **S1 Alignment**: success_criteria → 验证项
- **S2 Requirements**: PRD / User Stories + Acceptance Criteria（可测的）
- **S2 NFR**: 性能、可靠性、安全、可观测性、兼容性、数据正确性等
- **S3 Research**: 调研结论中的约束 → 兼容性/合规验证基线
- **S5 Solution**: 模块设计 + test_strategy → 测试方案依据
- **范围 & 变更记录**: 这次 release 包含什么、不包含什么（Scope lock）
- **构建与环境**: 可部署的 build、测试环境、账号/权限、测试数据/Mock、开关策略
- **可追溯矩阵（强烈建议）**: 需求 ↔ 测试用例 ↔ 缺陷 ↔ 发布版本

> 没有 AC/NFR 就只能"凭感觉测"，最后很容易扯皮、延期、带病上线。

---

## 关键活动（Activities）

### 1. 测试计划（Test Plan）与风险分层

先做风险分层，决定测试深度与优先级（否则资源永远不够）：

| 级别 | 说明 |
|------|------|
| P0 / 高风险 | 核心路径、资金/权限/数据不可逆、合规、安全、不可回滚改动 |
| P1 / 中风险 | 重要功能、常见场景、关键集成点 |
| P2 / 低风险 | 边角体验、低频场景、文案/样式 |

Test Plan 要写清：

1. 测试范围（in/out）
2. 测试类型与策略（见下方清单）
3. 环境/数据策略
4. 自动化范围
5. 缺陷管理与优先级标准
6. 退出标准（Exit criteria）与发布门禁（Go/No-Go）

---

### 2. 测试设计（Test Design）

把需求拆成可执行的测试资产：

- **测试用例（Test Cases）**: 覆盖核心路径 + 异常路径 + 边界条件
- **测试数据设计**: 有效/无效数据、边界值、特殊字符、空值、极端规模
- **接口/集成契约**: API 输入输出、错误码、幂等、重试、超时

**经验规则**：用例不要追求"数量"，追求"覆盖关键风险的最小集合"。

---

### 3. 测试执行（Execution）

常见执行顺序（可并行，但顺序很有用）：

1. **Smoke Test（冒烟）**: 验证 build 可用、关键路径能跑通（15-30 分钟内完成）
2. **Functional Test（功能）**: 按需求/用例验证正确性
3. **Integration Test（集成）**: 跨系统联调、权限、异步流程、消息队列、第三方
4. **Regression（回归）**: 对受影响模块与历史高风险点回归
5. **Exploratory（探索式）**: 补齐"文档没写但用户会做"的真实操作
6. **UAT（业务验收）**: 业务方/运营/客户成功确认可用与口径一致

---

## 测试类型清单

### A. 功能正确性（Functional）

- 核心用户旅程端到端（E2E）
- 权限/角色（RBAC）、状态流转、异常处理
- 输入校验、错误提示、重试/回滚逻辑

### B. 回归（Regression）

- 变更影响面：依赖模块、共享组件、公共服务
- 历史高发缺陷点（bug hotspot）

### C. 接口与契约（API/Contract）

- 错误码一致性、字段兼容、版本兼容
- 幂等、并发、超时、重试、限流
- backward compatibility（尤其对外 API）

### D. 性能与容量（Performance/Load）

- 关键接口 P95/P99 延迟
- 吞吐（TPS/QPS）、峰值压测、长稳（soak）
- 资源瓶颈（CPU/内存/连接池/队列堆积）

### E. 安全与合规（Security/Compliance）

- 权限绕过、越权访问、敏感数据泄露
- 审计日志、数据脱敏、加密传输/存储
- 依赖库漏洞扫描

### F. 可观测性与运维就绪（Observability/Operability）

- 关键指标埋点是否齐全（业务 + 系统）
- 日志能否定位问题（traceId、错误栈、关键字段）
- 告警阈值、仪表盘、值班手册、回滚脚本

### G. 兼容性与可用性（Compatibility/Usability）

- 浏览器/设备/分辨率（Web/移动端）
- 国际化/时区/货币（如涉及）
- 可访问性（如果是强要求领域）

---

## 缺陷管理

让 QA "推动闭环"，不是只提 bug。

### 缺陷分级

| 级别 | 说明 |
|------|------|
| Blocker / S0 | 阻塞测试或核心链路不可用、数据不可逆、重大安全/合规风险 |
| Critical / S1 | 核心功能错误、错误结果、频繁崩溃、无替代路径 |
| Major / S2 | 重要功能问题、有绕行方案、影响体验/效率 |
| Minor / S3 | 低影响、小瑕疵、文案/样式 |

### 缺陷报告最小模板

```markdown
## [模块] 现象描述

- **环境/版本/账号角色**:
- **复现步骤**:
  1. ...
  2. ...
  3. ...
- **预期结果**:
- **实际结果**:
- **影响范围**: 用户/数据/合规
- **附件**: 日志、截图、请求响应、traceId
- **严重级别**: S0/S1/S2/S3
- **优先级**: P0/P1/P2
```

> 最省时间的 bug 是"能一眼复现、能一眼定位"的 bug。

---

## 发布门禁（Go/No-Go）

### Exit Criteria（测试阶段退出）

- [ ] P0 用例通过率 = 100%（或明确例外并签字）
- [ ] S0/S1 缺陷 = 0（或有明确降级/规避方案并审批）
- [ ] 回归覆盖受影响区域（有覆盖证明）
- [ ] 性能指标达到 NFR（或有容量/限流/降级策略）
- [ ] 监控告警与回滚方案准备就绪
- [ ] 变更记录与发布说明完成（Release notes）

### Release Readiness（上线就绪）

- [ ] 灰度策略（比例、观察窗口、扩量条件）
- [ ] 回滚触发条件（指标阈值 + 操作步骤）
- [ ] On-call/值班安排与升级路径
- [ ] 数据迁移/脚本演练（如有）

---

## 自动化与 CI/CD

建议把自动化分层，不要一上来就 "All in E2E"：

| 层级 | 主责 | 特点 |
|------|------|------|
| Unit Tests | 开发 | 覆盖关键逻辑、边界条件（最快、最便宜） |
| API/Service Tests | QA | 稳定、性价比高（适合核心接口回归） |
| E2E Tests | QA | 少而精，只保留 P0 核心旅程（最脆、维护成本高） |

接入流水线：

- **PR 触发**: lint + unit + 快速 API
- **nightly**: 全量回归/长稳
- **release**: 冒烟 + P0 E2E + 关键性能基线

---

## 常见踩雷点与对策

| 踩雷点 | 对策 |
|--------|------|
| 需求不可测 | 强制每条 P0 需求必须有 AC（Given/When/Then） |
| 环境不稳定 | 先做环境冒烟 + 依赖服务健康检查 |
| 测试数据乱 | 建立可重复的数据种子/Mock、避免手工造数 |
| 频繁变更导致回归爆炸 | Scope freeze + 变更必须带影响面说明 |
| 只测 happy path | 强制异常路径覆盖（权限、网络、超时、并发） |
| 上线后才发现监控不够 | verification 阶段验收"可观测性用例" |

---

## 模板

### Test Plan（最小版目录）

```markdown
# Test Plan: {project_id}

## 1. Scope（in/out）
## 2. Risk Assessment（P0/P1/P2）
## 3. Test Types（Functional/Integration/Regression/Performance/Security/UAT）
## 4. Environments & Test Data
## 5. Automation Plan
## 6. Defect Triage & SLA
## 7. Exit Criteria & Go/No-Go
```

### Traceability Matrix（需求可追溯矩阵）

```markdown
| Requirement / User Story | AC | Test Case IDs | Automation? | Defects | Status |
|--------------------------|----|---------------|-------------|---------|--------|
| R1: ... | AC1.1, AC1.2 | TC-001, TC-002 | Yes | BUG-003 | Pass |
| R2: ... | AC2.1 | TC-003 | No | - | In Progress |
```
