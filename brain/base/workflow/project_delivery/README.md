# Project Delivery Workflow

这是一套面向项目需求处理与软件交付的 workflow 规范，目标发布位置是：

`/xkagent_infra/brain/base/workflow/project_delivery`

它覆盖的主闭环是：

`intake -> research -> bootstrap -> planning -> task modeling -> execution -> release -> audit -> feedback`

## 从哪里开始看

- 先看 [index.yaml](/xkagent_infra/brain/runtime/update_brain/pending/20260311_multicore_workflow/index.yaml)
  这里定义了目录结构、发布映射和入口文件。
- 再看 [DESIGN.md](/xkagent_infra/brain/runtime/update_brain/pending/20260311_multicore_workflow/DESIGN.md)
  这里解释整体目标、主流程、归属策略和目录布局。
- 然后看 [03_state_machines.yaml](/xkagent_infra/brain/runtime/update_brain/pending/20260311_multicore_workflow/03_state_machines.yaml)
  这是整套 workflow 的统一状态语义。

## 主入口

- [intake.yaml](/xkagent_infra/brain/runtime/update_brain/pending/20260311_multicore_workflow/04_workflows/intake.yaml)
- [research.yaml](/xkagent_infra/brain/runtime/update_brain/pending/20260311_multicore_workflow/04_workflows/research.yaml)
- [planning.yaml](/xkagent_infra/brain/runtime/update_brain/pending/20260311_multicore_workflow/04_workflows/planning.yaml)
- [task_modeling.yaml](/xkagent_infra/brain/runtime/update_brain/pending/20260311_multicore_workflow/04_workflows/task_modeling.yaml)
- [execution.yaml](/xkagent_infra/brain/runtime/update_brain/pending/20260311_multicore_workflow/04_workflows/execution.yaml)
- [release.yaml](/xkagent_infra/brain/runtime/update_brain/pending/20260311_multicore_workflow/04_workflows/release.yaml)
- [audit.yaml](/xkagent_infra/brain/runtime/update_brain/pending/20260311_multicore_workflow/04_workflows/audit.yaml)
- [07_feedback_loop.yaml](/xkagent_infra/brain/runtime/update_brain/pending/20260311_multicore_workflow/07_feedback_loop.yaml)

## 目录说明

- `workflow/`
  主流程定义。
- `contracts/`
  状态机、schema、ID 规范、execution/release/audit 契约。
- `models/`
  planning、task、environment、runtime 分层模型。
- `governance/`
  observability、timeline、feedback、failure paths、archive、watchdog 等治理规则。
- `protocols/`
  control/runtime IPC 与事件 schema。
- `implementation/`
  实施计划和 backlog。

## 发布说明

- 当前目录是 proposal 工作区。
- 正式发布时，文件名会按 `index.yaml.publish_mapping` 和 `proposal_to_publish_rename` 映射到稳定名字。
- 发布目标是完整目录，不是只挑单文件散放。
