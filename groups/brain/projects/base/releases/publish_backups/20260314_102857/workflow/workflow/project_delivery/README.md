# Project Delivery Workflow

这是一套面向项目需求处理与软件交付的 workflow 规范，目标发布位置是：

`/xkagent_infra/brain/base/workflow/project_delivery`

它覆盖的主闭环是：

`intake -> research -> bootstrap -> planning -> task modeling -> execution -> release -> audit -> feedback`

为了解决“workflow 写了很多，但项目是否逐条做到并不透明”的问题，这个 package 现在要求项目维护一份 `spec checklist`：

- 它把 workflow 要求点实例化成项目级清单
- 它记录总点数、已完成点、阻塞点、waive 点和 evidence
- audit 不是唯一发现问题的入口，execution 期间也必须持续更新这份完成度台账

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

## 新增关键契约

- `SPEC_CHECKLIST.yaml`
  workflow 标准执行清单，定义一次完整执行至少要完成多少个 base items。
- `contracts/spec_checklist_contract.yaml`
  定义 workflow 标准清单与项目执行实例的关系、完成度算法和 audit 复核规则。

## Agent 快速指南

- `SPEC_CHECKLIST_GUIDE.md`
  给执行 agent 的短指南，说明标准清单怎么实例化、怎么更新、什么情况不能算完成。
- `spec_checklist.instance.template.yaml`
  项目级实例模板，复制后落到 `project_root/spec/spec_checklist.yaml`。

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
