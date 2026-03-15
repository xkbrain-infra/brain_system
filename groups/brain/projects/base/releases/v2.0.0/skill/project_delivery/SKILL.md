---
name: project_delivery
description: 使用 brain project_delivery workflow 处理项目交付、规划、执行、发布与审计。
metadata:
  status: draft
  source_project: /xkagent_infra/groups/brain/projects/base
  publish_target: /xkagent_infra/brain/base/skill/project_delivery
---

# Project Delivery

该 skill 绑定 `projects/base` 中的 `workflow/project_delivery` 能力包。

使用目标：
- 引导 agent 按 project delivery workflow 工作
- 将 workflow 中的关键阶段映射为实际执行步骤
- 与同项目下的 hooks 配合，减少偏离流程的操作

依赖：
- workflow: `/xkagent_infra/groups/brain/projects/base/workflow/project_delivery`
- hooks: `/xkagent_infra/groups/brain/projects/base/hooks/overrides/project_delivery`

发布说明：
- project 侧完成设计后，发布到 `/xkagent_infra/brain/base/skill/project_delivery`
