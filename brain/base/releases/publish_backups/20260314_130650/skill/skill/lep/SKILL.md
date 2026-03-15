---
name: lep
description: 解释和执行 Brain 的 LEP 门控工作方式；当任务涉及受保护路径、审批、Plan 原子化、范围限制、被 hooks 拦截后的修正，或用户要求遵守 LEP/门控/治理规则时使用。
metadata:
  status: active
  source_project: /xkagent_infra/groups/brain/projects/base
  publish_target: /xkagent_infra/brain/base/skill/lep
---

# LEP

这个 skill 负责把 LEP 从“只会拦截的 hooks”补成“agent 可执行的操作手册”。

使用目标：
- 解释当前操作为什么会被 LEP 拦截
- 在真正动手前收敛出符合 LEP 的计划、审批链和 scope
- 把 role / agent / workflow 绑定到的 LEP profile 转成实际行为

优先读取：
- `/brain/base/spec/core/lep.yaml`
- `/brain/base/spec/policies/lep/index.yaml`

按需读取：
- 某个具体 gate 对应的 `/brain/base/spec/policies/lep/<gate>.yaml`
- LEP hooks 作用域规则：`/brain/base/hooks/lep/role_scope.py`

## 工作方式

1. 先确认本次任务的 LEP 上下文
   - 当前 role / agent / workflow 是什么
   - 已启用哪些 LEP profiles
   - 当前操作属于 read / write / delete / move / git 哪一类

2. 在执行前做 LEP 对齐
   - 涉及修改时先确认是否需要 Plan
   - Plan 必须原子化到文件和动作
   - 涉及审批/委派时先走 PMO / IPC
   - 涉及受保护路径时先确认 scope 和回滚策略

3. 如果被 hooks 拦截
   - 不要盲目重试
   - 先读对应 gate 文件
   - 调整计划、范围、审批链或验证步骤
   - 只有修正了阻断原因，才继续执行

## 常见场景

- 改 `/brain/base/spec`、`/brain/base/workflow`、`/brain/infrastructure`
- 执行删除、迁移、批量改动、数据库变更、部署操作
- 被提示 `No Action Without Plan`、`Scope Locking`、`Approval Delegation`
- 需要判断“这次为什么被拦截，应该怎么改才对”

## 与 hooks 的关系

- hooks 负责强制执行
- prompt 负责提醒
- 这个 skill 负责解释规则并给出可执行修正路径

## 与 bindings 的关系

LEP profile 绑定来自：
- `/xkagent_infra/brain/infrastructure/config/agentctl/lep_bindings.yaml`

解析顺序：
1. `workflow.required_lep_profiles`
2. `agent.extra_lep_profiles`
3. `role.default_lep_profiles`

你应当把这些 profiles 当作强约束，不是建议。
