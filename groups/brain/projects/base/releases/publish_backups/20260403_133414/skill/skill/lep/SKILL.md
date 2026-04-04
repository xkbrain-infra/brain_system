---
id: G-SKILL-LEP
name: lep
description: "当操作被 hooks 拦截、执行前需要 LEP 对齐、或需要理解 gate 规则时使用。"
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Bash
argument-hint: "[check|unblock|explain] [gate_id]"
metadata:
  status: active
  source_project: /xkagent_infra/groups/brain/projects/base
  publish_target: /xkagent_infra/brain/base/skill/lep
  spec_ref: /brain/base/spec/core/lep.yaml
---

# LEP

<!-- L1 -->
## 触发场景

| 情境 | 跳转 |
|------|------|
| 被 hooks 拦截，不知道怎么修正 | → [解除拦截](#解除拦截) |
| 执行写/删/移操作之前 | → [执行前对齐](#执行前对齐) |
| 需要理解某个 gate 的规则 | → [查询 Gate 规则](#查询-gate-规则) |
| 涉及审批 / PMO 委派 | → [执行前对齐 § 审批链](#执行前对齐) |

不适用：
- 纯读操作（read 类不触发大多数 gate）
- 已有 approved Plan 且 scope 已确认的执行阶段

---

<!-- L2 -->
## 执行前对齐

> 深入规则：`spec_ref § universal_gates`

执行任何 write / delete / move / git 操作前，依次确认：

1. **是否需要 Plan？** — G-GATE-NAWP
   - 有修改操作 → 必须先有 Plan，且 PMO 已批准
2. **Plan 是否原子化？** — G-GATE-ATOMIC
   - Plan 必须具体到文件路径 + 动作，不能是模糊描述
3. **操作是否在 scope 内？** — G-GATE-SCOP
   - 确认操作路径在当前 agent 的允许范围内
4. **是否可回滚？** — G-GATE-ROLLBACK-READY
   - 修改前确认备份策略或 git 快照

---

## 解除拦截

> 深入规则：读取对应 gate 文件 `spec_ref/policies/lep/<gate_id>.yaml`

被拦截后的标准步骤：

1. **识别 gate** — 读拦截消息中的 gate ID（如 `G-GATE-NAWP`）
2. **读 gate 文件** — `/brain/base/spec/policies/lep/<gate_name>.yaml`
3. **找阻断原因** — 检查 `rule` 字段，对照自己的操作
4. **修正计划** — 按 gate 要求补充 Plan / 审批 / scope / 备份
5. **重新执行** — 只有修正了阻断原因才继续，不要盲目重试

常见 gate 对应文件：

| Gate ID | 文件 |
|---------|------|
| G-GATE-NAWP | `policies/lep/nawp.yaml` |
| G-GATE-SCOP | `policies/lep/scop.yaml` |
| G-GATE-ATOMIC | `policies/lep/atomic.yaml` |
| G-GATE-ROLLBACK-READY | `policies/lep/rollback_ready.yaml` |
| G-GATE-FILE-HIERARCHY | `policies/lep/file_hierarchy.yaml` |
| G-GATE-DELETE-BACKUP | `policies/lep/delete_backup.yaml` |

---

## 查询 Gate 规则

```bash
# 查看所有 universal gates
cat /brain/base/spec/core/lep.yaml

# 查看某个具体 gate
cat /brain/base/spec/policies/lep/<gate_name>.yaml

# 查看当前 agent 的 LEP profile 绑定
cat /xkagent_infra/brain/infrastructure/config/agentctl/lep_bindings.yaml
```

LEP profile 解析顺序：
1. `workflow.required_lep_profiles`
2. `agent.extra_lep_profiles`
3. `role.default_lep_profiles`

---

## Spec 引用

| 场景 | 读取路径 | 读取时机 |
|------|----------|----------|
| 全部 universal gates | `spec_ref § universal_gates` | 执行前对齐时 |
| 具体 gate 规则 | `spec_ref/policies/lep/<gate>.yaml` | 被拦截后 |
| LEP profile 绑定 | `lep_bindings.yaml` | 查询当前 agent 约束时 |
| hooks 作用域 | `/brain/base/hooks/lep/role_scope.py` | 理解 hook 触发范围时 |

`spec_ref` = `/brain/base/spec/core/lep.yaml`
