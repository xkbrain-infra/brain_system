# Solution 阶段指南

> 适用于 S5 Solution 阶段的技术设计作战手册。Owner: **architect** 主导，**qa** + **devops** 同步参与。
> 不是随便画个方案图，而是把"已拍板的需求 + 约束 + 风险"落成一套可实现、可验证、可运维、可演进的解决方案。
>
> - Schema: `/brain/base/spec/templates/spec/spec_dsl.yaml#solution`
> - 流程: `/brain/base/workflow/lifecycle/project.yaml#S5`

---

## 目标（6 件事）

1. **实现路径明确**: 架构、组件边界、接口/事件/数据契约清晰
2. **关键风险被工程化消解**: 通过 POC/Spike 把不确定性打掉
3. **非功能需求可落地**: 性能/可靠性/安全/可观测性/成本都有设计对应物
4. **可测试**: 每个关键需求都能映射到测试策略与验收标准
5. **可发布/可回滚**: 灰度、feature flag、迁移方案、回滚策略设计完备
6. **可演进**: 版本策略、兼容策略、未来扩展点预留，不留技术债"地雷"

---

## 输入（Inputs）

没有这些输入，solution 很容易"漂亮但不可落地"：

| 来源 | 消费什么 |
|------|----------|
| S1 Alignment | goal、scope、constraints → 设计边界 |
| S2 Requirements | must-have、NFR（量化） → 功能模块 + 非功能约束 |
| S3 Research | viable_directions、技术调研 → 技术选型依据 |
| S4 Analysis | chosen option、trade-off → 确定的方案路线、依赖与约束 |

---

## 产出（Deliverables）

solution 产出必须**可执行、可验证、可交接**。

### A. Solution Overview（1-2 页总览）

- 目标、范围、核心用户旅程
- 高层架构图（系统边界、数据流、调用关系）
- 关键决策摘要（含取舍）
- 关键风险与缓解策略
- 里程碑与依赖

### B. Detailed Design（按模块拆）

#### 1. Architecture & Component Design

- 模块边界、职责、接口（同步/异步）
- 关键流程：时序图/状态机（尤其是异步、回滚、补偿）
- 可扩展点：插件机制、策略模式、可配置项

#### 2. API / Event Contracts（契约是硬标准）

- **API**: 路径、请求/响应 schema、错误码、鉴权、幂等、分页、版本
- **事件**: topic、schema、投递语义（at-least-once 等）、顺序要求、DLQ
- **向后兼容策略**: 字段新增/废弃/默认值规则

#### 3. Data Design

- 数据模型（表结构/索引/分区/血缘）
- 数据质量规则（唯一性、完整性、范围、对账口径）
- 迁移方案（backfill、双写、读写切换）

#### 4. NFR Design（必须"设计可验证"）

- **性能**: 容量估算、缓存策略、限流/熔断/降级
- **可靠性**: 重试、幂等、补偿、RPO/RTO（如要求）
- **安全**: RBAC、审计日志、敏感数据处理、密钥/secret 管理
- **可观测性**: 指标、日志字段、trace 贯穿、告警阈值
- **成本**: 云资源、存储、推理成本（如 AI）

### C. Test Strategy（和 solution 强绑定）

- 分层测试：unit / api / contract / integration / e2e（P0 核心旅程少而精）
- 测试数据策略：可重复生成、mock/stub、环境健康检查
- 关键 NFR 测试：压测/长稳/故障演练/安全测试

### D. Release & Rollback Plan（上线方案）

- feature flag 策略、灰度扩量条件、回滚触发条件
- 兼容/迁移：双写、shadow read、逐步切流
- runbook：常见故障处理、值班升级路径

### E. POC / Spike 结论（高要求项目必备）

- 关键技术难点验证：性能瓶颈、依赖限制、数据质量、模型效果等
- 量化结果（而不是"感觉可行"）
- 结论：继续/调整/降级

### F. Decision Log / ADR

- 关键架构/技术选择的记录：为什么、替代方案为何不选、后果是什么、何时复盘

---

## 执行流程

### Step 1: 把需求映射成"设计对象"

- 每条 P0 需求 → 对应模块/接口/数据/流程 → 对应 AC & 测试点
- 产出：**需求-设计-测试可追溯矩阵**（防止遗漏）

### Step 2: 先解决"不可逆风险"

按风险优先级做 POC/Spike：

- 数据迁移/一致性
- 权限/合规
- 性能与容量（P95/P99、峰值）
- 关键依赖的限制（配额/限流/兼容）

### Step 3: 契约先行（Contract-first）

- API schema / event schema 定稿并进入版本治理
- 设计阶段就定义：错误码、幂等、超时、重试策略

### Step 4: NFR 设计"落到可测阈值"

把 NFR 写成能验证的门槛：

- 例如：P95 < 200ms；error rate < 0.1%；审计事件覆盖 100%；回滚 ≤ 10min

### Step 5: 发布与回滚"从第一天设计"

- feature flag、灰度扩量、回滚与数据补偿必须在设计里出现
- 对数据改动：一定要有 backfill 与回退策略

---

## 模块设计模板

```yaml
- id: M-001
  name: "模块名"
  responsibilities: "职责描述"
  io:
    input: "输入（数据格式、来源）"
    output: "输出（数据格式、去向）"
  dependencies: "依赖的模块/服务"
  interfaces:
    - path: "/api/v1/xxx"
      method: "POST"
      request_schema: "{ field: type }"
      response_schema: "{ field: type }"
      error_codes: [400, 401, 403, 404, 409, 500]
      auth: "Bearer token + RBAC"
      idempotent: true
  state_machine:
    states: [created, processing, completed, failed]
    transitions:
      - from: created
        to: processing
        trigger: "start_processing()"
        guard: "all dependencies ready"
      - from: processing
        to: failed
        trigger: "error occurred"
        action: "retry 3x → alert → manual intervention"
  failure_modes:
    - scenario: "下游服务超时"
      impact: "请求失败"
      handling: "重试 3 次，指数退避，最终降级返回缓存数据"
    - scenario: "数据不一致"
      impact: "业务逻辑错误"
      handling: "对账 job 检测 + 告警 + 手动修复 runbook"
  test_strategy:
    unit: "核心逻辑 + 边界条件"
    api: "happy path + error codes + auth + idempotent"
    integration: "与下游服务联调 + 超时/重试行为"
    acceptance: "S2 R1 验收标准"
  observability:
    metrics: ["request_count", "latency_p95", "error_rate"]
    logs: ["request_id", "user_id", "action", "result"]
    alerts:
      - condition: "error_rate > 1%"
        severity: P1
      - condition: "latency_p95 > 500ms"
        severity: P2
```

---

## NFR 设计条目模板

| NFR 类别 | 指标/阈值 | 设计手段 | 验证方法 | 观测/告警 |
|----------|-----------|----------|----------|-----------|
| 性能 | P95/P99、QPS | 缓存/索引/队列 | 压测/长稳 | dashboard + 告警 |
| 可靠性 | error rate、RTO | 重试/幂等/降级 | 故障演练 | 告警阈值 |
| 安全 | RBAC/审计覆盖 | 权限模型/日志 | 安测用例 | 审计检查 |
| 可观测性 | trace 覆盖率 | 埋点/日志规范 | 验收用例 | 仪表盘 |
| 成本 | $/day 上限 | 资源配额/批处理 | 成本回归 | 成本告警 |

---

## Solution Brief（1 页模板）

```markdown
# Solution Brief: {project_id}

## Problem / Goal

## Scope（in/out）& MVP

## Key Metrics & NFR

## High-level Architecture（图）

## Key Flows（时序/状态）

## Contracts（API/Event/Data Schema）

## Risks & Mitigations（含 POC 结果）

## Release & Rollback Strategy

## Open Questions & Decision Owners
```

---

## 完成标准（Exit Criteria）

- [ ] **核心流程闭环**: 主链路 + 异常链路 + 回滚/补偿都有设计（图 + 文字）
- [ ] **契约定稿**: API/event/schema、错误码、鉴权、幂等、版本策略明确
- [ ] **数据方案可迁移**: 迁移步骤、回填、切流、回退路径清晰
- [ ] **NFR 可验证**: 性能/可靠性/安全/观测/成本都有量化阈值 + 对应设计手段
- [ ] **测试策略可执行**: 分层测试范围、P0 E2E 列表、契约测试计划已出
- [ ] **发布方案可操作**: 灰度/开关/回滚/runbook 完备
- [ ] **关键风险已通过 POC/Spike 降低**（有数据结论）
- [ ] **ADR/决策记录齐全**，可追溯
- [ ] **qa 参与确认**: 每个模块有 test_strategy

---

## 常见雷区

| 雷区 | 守门方式 |
|------|----------|
| 只画架构图，不落契约 | 强制 API/event/schema + 错误码 + 版本策略 |
| 只考虑 happy path | 强制异常路径、补偿/回滚、幂等、重试语义 |
| NFR 写口号 | 强制量化阈值 + 验证方法 + 监控告警 |
| 上线方案最后补 | solution 阶段必须包含灰度/开关/回滚/runbook |
| POC 缺失 | 对高风险点必须用数据证明可行，否则降级/缩 scope |
| architect 独自设计完交出去 | qa + devops 必须同步参与，否则测试和部署都会出问题 |
| 状态机只列状态不画转换 | 必须有完整的转换条件 + 异常处理 |
| 可观测性没设计 | 每个模块必须有 metrics/logs/alerts 定义 |

---

## 建议

给 solution 阶段加一个固定评审：**Solution Review**（架构 + 测试 + 发布联合评审），用上面的 Exit Criteria 当门禁，一次性把 architect/qa/devops 的关切点对齐，后面能省非常多返工。
