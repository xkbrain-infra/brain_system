# S9 审计指南 (Audit Guide)

> 本阶段由 QA agent 独立执行，对照 project spec + brain spec 逐项检查合规性。
> QA 在此阶段作为**独立审计方**，不受项目当事人影响。

## 目标

1. 验证 S0-S8 所有阶段的产出物是否完整、格式正确
2. 验证代码是否符合 brain 系统规范（LEP gates）
3. 验证执行期间发现的问题（ISS）是否全部解决
4. 识别需要反馈到 base 的改进点

## 审计流程

### Step 1: 读取项目元信息

```yaml
actions:
  - Read index.yaml → 获取项目 id、status、agents 列表
  - Read project.yaml → 获取所有 validate 规则和 checklist
  - 确认 index.yaml status 已到 S8 complete
```

### Step 2: 逐阶段检查产出物

对照 project.yaml 中每个 step 的 `validate` 规则，逐项检查：

| 阶段 | 检查项 | 怎么查 |
|------|--------|--------|
| S0 | 目录结构完整 | ls 项目目录 |
| S0 | index.yaml 字段齐全 | Read + 检查 id/title/status/agents |
| S0 | 6 个 agent 已创建 | agentctl list 确认 |
| S1 | 01_alignment.yaml 存在且非空 | Read + 检查 goal/in_scope |
| S2 | 02_requirements.yaml must >= 1 | Read + count must items |
| S3 | 03_research.yaml findings 有 sources | Read + 检查 URL |
| S3 | references/ 下有 SR-*.md 文件 | Glob 检查 |
| S4 | 04_analysis.yaml decision 非空 | Read + 检查 decision.chosen |
| S4 | role_opinions 至少有 architect | Read + 检查字段 |
| S5 | 05_solution.yaml modules 非空 | Read + 检查 |
| S5 | 每个 module 有 test_strategy | 遍历 modules 检查 |
| S6 | 06_tasks/ 目录结构完整 | ls 检查 plan/backlog/assigned/done/task_manager |
| S6 | task_manager.yaml 有 execution_log | Read + 检查 |
| S6 | 无 06_tasks.yaml 扁平文件 | 确认不存在 |
| S7 | 4 份报告齐全 | ls spec/07_verification/reports/ |
| S7 | summary.yaml decision 非空 | Read + 检查 |
| S8 | retrospective 有 task_report | Read + 检查 |

### Step 3: Brain Spec 合规检查

```yaml
checks:
  G-GATE-VERIFICATION:
    method: "检查代码是否有对应测试，测试是否通过"
    evidence: "pytest 输出或测试结果文件"

  G-GATE-PATH-DISCIPLINE:
    method: "检查产出文件是否在正确路径下"
    evidence: "文件路径列表 vs 规范路径"

  conflict_markers:
    method: "grep -r '^<<<<<<<' 在代码目录中搜索"
    evidence: "grep 结果（应为空）"

  credentials:
    method: "grep -ri 'password\\|secret\\|api_key\\|token' 在代码中搜索"
    evidence: "grep 结果（排除合理引用后应为空）"
```

### Step 4: Issues 收尾检查

```yaml
checks:
  - "journal/issues/ 中所有 ISS 的 resolved_at 非空"
  - "base_upgrade_candidate=true 的 ISS 已有对应 pending_base 条目"
  - "无 severity=high 的未解决 ISS"
```

### Step 5: 产出审计报告

写入 `journal/audit/audit_report.yaml`：

```yaml
audit:
  project_id: "BS-024-health-check"
  auditor: "agent_bs024_qa"
  audit_date: "2026-02-22"
  
  summary:
    total_checks: 25
    passed: 23
    failed: 1
    warnings: 1
  
  items:
    - check_id: AUD-001
      category: project_spec
      stage: S0
      check: "项目目录结构完整"
      result: pass
      evidence: "ls 确认 references/, spec/, memory/ 存在"

    - check_id: AUD-015
      category: project_spec
      stage: S6
      check: "task_manager.yaml 有 execution_log"
      result: fail
      evidence: "task_manager.yaml 不存在，使用了扁平 06_tasks.yaml"
      recommendation: "下次项目 orchestrator 必须使用目录结构"
      severity: high

  conclusion:
    decision: "pass / conditional_pass / fail"
    conditions: "如 conditional_pass，列出必须修复的项"
    base_upgrade_items:
      - "ISS-001: S6 需要在 workflow 中标注文件写权限要求"
```

### Step 6: 上报结果

```yaml
actions:
  - "审计通过 → ipc_send(to=pmo, '[AUDIT] BS-024 审计通过，可归档')"
  - "审计失败 → ipc_send(to=pmo, '[AUDIT] BS-024 审计失败，N 项不合规，需返工')"
  - "PMO 确认后更新 index.yaml status: archived"
  - "agentctl purge 所有项目 agents"
```

## 审计原则

1. **独立性**：审计 agent 不应是项目执行的参与者（理想情况）。如果 QA 同时参与了 S7 验收，审计时要特别注意自审盲区。
2. **证据为王**：每个 check 必须有 evidence（文件路径、命令输出），不能写"看起来OK"。
3. **不修不审**：审计只检查不修复。发现问题记录到 audit_report，由 PMO 决定是否返工。
4. **base 反馈**：审计是发现 base 改进点的重要来源，`base_upgrade_candidate` 必须认真填写。
