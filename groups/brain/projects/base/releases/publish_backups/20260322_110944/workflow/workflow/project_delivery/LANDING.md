# Project Delivery Index

发布目标：

`/xkagent_infra/brain/base/workflow/project_delivery`

## 快速入口

- 目录说明：`README.md`
- 设计总览：`DESIGN.md`
- 标准清单：`SPEC_CHECKLIST.yaml`
- 实例模板：`spec_checklist.instance.template.yaml`
- Agent 操作：`SPEC_CHECKLIST_GUIDE.md`
- 发布映射：`index.yaml`
- 发布批次：`MANIFEST.proposal.yaml`

## 主流程

- `workflow/intake.yaml`
- `workflow/research.yaml`
- `workflow/bootstrap.yaml`
- `workflow/planning.yaml`
- `workflow/task_modeling.yaml`
- `workflow/execution.yaml`
- `workflow/release.yaml`
- `workflow/audit.yaml`

## 核心契约

- `SPEC_CHECKLIST.yaml`
- `contracts/state_machines.yaml`
- `contracts/spec_checklist_contract.yaml`
- `contracts/unified_schemas.yaml`
- `contracts/identifier_conventions.yaml`
- `governance/observability.yaml`
- `governance/feedback_loop.yaml`

## 建议阅读顺序

1. `README.md`
2. `DESIGN.md`
3. `contracts/state_machines.yaml`
4. `workflow/intake.yaml` 到 `workflow/audit.yaml`
5. `governance/feedback_loop.yaml`

## 一句话说明

这是一套面向项目需求处理与软件交付的 workflow 规范，覆盖从 intake 到 audit/feedback 的完整闭环。
