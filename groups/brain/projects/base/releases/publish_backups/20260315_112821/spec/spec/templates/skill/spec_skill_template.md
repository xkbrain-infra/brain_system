---
id: G-SKILL-<DOMAIN>-<NAME>
name: <name>
description: "<一句话触发条件：当 agent 遇到 X 场景时调用此 skill>"
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Edit, Bash, Glob
argument-hint: "[<arg1>|<arg2>] [options]"
metadata:
  status: active
  source_project: /xkagent_infra/groups/brain/projects/base
  publish_target: /xkagent_infra/brain/base/skill/<name>
  spec_ref: /brain/base/spec/policies/<domain>/<spec_file>.yaml
---

# <Skill Name>

<!-- L1: 触发场景 — 帮助 agent 确认是否在正确场景 -->
## 触发场景

- 场景 A：...
- 场景 B：...
- 场景 C：...

不适用：
- X 情况下不需要此 skill（直接做什么即可）

---

<!-- L2: 执行入口 — 根据场景路由，只暴露当前分支 -->
## 执行入口

根据你的情境选择分支：

| 情境 | 跳转 |
|------|------|
| 场景 A | → [流程 A](#流程-a) |
| 场景 B | → [流程 B](#流程-b) |
| 不确定 | → 先回答：[我需要做什么？](#我需要做什么) |

---

<!-- L3: 具体流程 — 按需加载，执行到此步再读 -->
## 流程 A

> 深入规则：读取 `<spec_ref>` 的 `<section>` 段

1. **步骤 1** — ...
2. **步骤 2** — ...
3. **验证** — ...

---

## 流程 B

> 深入规则：读取 `<spec_ref>` 的 `<section>` 段

1. **步骤 1** — ...
2. **步骤 2** — ...

---

## 我需要做什么

提问帮助路由：

1. 你的目标是什么？
2. 当前处于哪个阶段？
3. 是否已有 Plan？

---

## Spec 引用

| 场景 | 读取路径 | 读取时机 |
|------|----------|----------|
| 场景 A 详细规则 | `<spec_ref>#<section_a>` | 进入流程 A 时 |
| 场景 B 详细规则 | `<spec_ref>#<section_b>` | 进入流程 B 时 |
| 验证清单 | `<spec_ref>#validation` | 执行完成后 |
