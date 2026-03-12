# Multicore Workflow Design

## 目标

为 `brain infra` 引入一套适配多 sandbox / 多 orchestrator 的统一 workflow 设计，使系统同时具备：

- 单一主脑与多项目隔离
- 完整交付导向，而不是 MVP / demo 导向
- 项目级编排 owner
- 全局任务与状态可见性
- 结构化日志与时间线可追溯性
- 中心化配置、端口、service 注册与 supervisor 注册
- 发布闭环
- 审计闭环
- knowledge / evolution 反馈闭环

## 核心判断

### 1. `brain` 只能有一个

`brain` 应作为唯一 control plane 常驻主容器，负责治理、注册、观测、协调，不直接承担具体项目执行。

### 2. 每个项目应运行在独立 sandbox

`sandbox` 是隔离执行环境的设计模式，不绑定单一实现。

每个项目必须运行在独立 sandbox 中，拥有自己的代码副本、workspace、依赖、agents、runtime 和项目上下文。

当前批准的默认实现是 `docker_container`，但它只是 `sandbox` 的一种 provider，而不是 `sandbox` 本身的定义。

对于 `docker_container` provider，必须先从内置 Docker 模板实例化，再按项目做适配；不得临时自由发挥，也不得把宿主机目录误当作 sandbox。

### 3. 每个 sandbox 必须有自己的 `project orchestrator`

项目级 owner 不是 brain，也不是 manager，而是 sandbox 内的 orchestrator。它负责：

- 接收项目目标
- 初始化项目 plan
- 拆 task 与分配 agent
- 推进 coding / test / review / release prep
- 处理 blocked / retry / replan
- 向全局同步项目状态

### 4. `task manager` 仍然保留，但重新定位

`task manager` 不只是任务表，而是全局状态汇聚层，负责：

- project / task / agent / orchestrator 状态索引
- 心跳和超时观测
- manager 视图与治理事件入口
- 发布 gate 与审计输入

不建议它直接吞掉项目内所有执行逻辑。

## 分层

### Brain Infra

职责：

- SSOT / workflow registry / spec / governance
- sandbox 生命周期管理
- config registry service
- global task manager
- control IPC
- release manager
- audit orchestrator
- cross-project coordination

### Project Sandbox

职责：

- 承载来自 group project root 的执行副本
- 项目 workspace
- 完整 brain 基线副本上的项目工作副本
- runtime IPC
- project orchestrator
- worker agents
- 本地 task runtime
- 项目内 build/test/review/release 执行环境

### Manager / PMO

职责：

- 需求 intake
- go / no-go
- 资源批准
- 风险与 scope 决策
- 生产发布批准

## 闭环定义

系统闭环不是 “任务完成”，而是：

`intake -> research -> bootstrap -> planning -> task modeling -> execution -> sync -> escalation -> release -> audit -> feedback`

项目只有在以下条件都完成后才算真正结束：

- project deliverables 完成
- release 执行完成或显式回滚
- audit report 完成
- improvement actions 进入 knowledge / workflow / evolution

## 主流程顺序

当前 multicore workflow 的推荐主流程顺序为：

1. `profile`
2. `intake`
3. `research`
4. `bootstrap`
5. `planning`
6. `task modeling`
7. `execution`
8. `release`
9. `audit`
10. `feedback`

说明：

- `intake` 只做入口受理与立项前最小条件检查
- `research` 为 planning 提供参考方案与风险输入
- `planning` 先形成 project plan，再进入 task modeling
- `task modeling` 是 plan 的实例化，而不是 planning 本身

## 设计件

本提案包含以下设计件：

1. `01_architecture_overview.yaml`
2. `02_domain_model.yaml`
3. `03_state_machines.yaml`
4. `04_workflows/*.yaml`
5. `05_protocols/*.yaml`
6. `06_observability.yaml`
7. `07_feedback_loop.yaml`
8. `15_workflow_profiles.yaml`
9. `16_timeline_and_reporting.yaml`
10. `17_task_supervision.yaml`
11. `18_environment_baseline.yaml`
12. `docker_sandbox_template.yaml`
13. `19_unified_schemas.yaml`
14. `20_identifier_conventions.yaml`
15. `31_logging_service.yaml`
16. `32_logging_schema_and_storage.yaml`
17. `33_config_registry_service.yaml`
18. `34_service_registration_flow.yaml`
19. `35_runtime_config_schema.yaml`
20. `36_service_prompt_contract.yaml`
21. `37_config_registry_protocol.yaml`
22. `38_config_registration_sequences.yaml`
23. `39_brain_manager_publish_service.yaml`
24. `40_runtime_package_publish_flow.yaml`
25. `41_publish_validation_and_promotion.yaml`
26. `42_service_rollout_order.yaml`
27. `43_minimum_runtime_topology.yaml`
28. `44_failure_paths.yaml`
29. `45_sync_and_watchdog_contract.yaml`
30. `46_config_registry_storage.yaml`
31. `47_sandbox_archive_contract.yaml`
32. `48_rollout_degrade_modes.yaml`

## 发布归属

这套设计发布后不应继续留在 `runtime/update_brain/pending`，而应进入 `brain/base/workflow/project_delivery`。

建议发布位置：

```text
/brain/base/workflow/project_delivery/
  index.yaml
  DESIGN.md
  CHANGELOG.pending.md
  workflow/
    intake.yaml
    bootstrap.yaml
    research.yaml
    planning.yaml
    task_modeling.yaml
    execution.yaml
    global_sync.yaml
    escalation.yaml
    release.yaml
    audit.yaml
  contracts/
    state_machines.yaml
    unified_schemas.yaml
    identifier_conventions.yaml
    task_manager_role.yaml
    timer_trigger_model.yaml
    execution_contract.yaml
    release_contract.yaml
    audit_contract.yaml
    logging_service.yaml
    config_registry_service.yaml
    runtime_config_schema.yaml
    service_prompt_contract.yaml
    brain_manager_publish_service.yaml
  models/
    architecture_overview.yaml
    domain_model.yaml
    workflow_profiles.yaml
    environment_baseline.yaml
    docker_sandbox_template.yaml
    planning_model.yaml
    planning_detail_model.yaml
    task_modeling_rules.yaml
    task_modeling_examples.yaml
    parallel_execution_model.yaml
    local_vs_global_runtime.yaml
    research_and_benchmark.yaml
    minimum_runtime_topology.yaml
  governance/
    observability.yaml
    feedback_loop.yaml
    compatibility_mapping.yaml
    failure_paths.yaml
    sync_and_watchdog_contract.yaml
    config_registry_storage.yaml
    sandbox_archive_contract.yaml
    sequence_flows.yaml
    timeline_and_reporting.yaml
    task_supervision.yaml
    release_gate_definitions.yaml
    audit_review_model.yaml
    logging_schema_and_storage.yaml
    service_registration_flow.yaml
    config_registration_sequences.yaml
    runtime_package_publish_flow.yaml
    publish_validation_and_promotion.yaml
    service_rollout_order.yaml
    rollout_degrade_modes.yaml
  protocols/
    control_ipc.yaml
    runtime_ipc.yaml
    event_schema.yaml
    config_registry_protocol.yaml
  implementation/
    IMPLEMENTATION_PLAN.md
    implementation_backlog.yaml
```

说明：

- `architecture_overview.yaml` 是 package 入口之一，不单独悬挂
- `index.yaml` 负责声明本 workflow package 的边界、用途、引用关系和发布映射
- 当前 `pending` 中带编号的文件名仅用于提案阶段，正式发布时应切换为稳定文件名
- 发布时应按照 `index.yaml.publish_mapping` 做逐文件映射，而不是手工散放

## 归属策略

- 这套内容整体归属于 `base/workflow/project_delivery`
- workflow 规范、状态机、gate、reporting、audit closure 一起发布
- 偏基础设施实现的 service 代码仍留在 `infrastructure` 或 `runtime`，这里只保留 workflow 规范与所需契约说明

## 当前缺口的补齐原则

本提案默认采用 `software_dev` profile，并明确补齐以下执行细节：

- `project_delivery` 以完整交付为目标；任何 MVP / phase-1 / demo 压缩都必须显式审批
- `sandbox` contract 与 provider/template/adaptation 分层
- 默认 `docker_container` provider 的固定模板资产、实例化规则和项目适配边界
- 项目必须先归属 group，并在 `groups/{group}/projects/{project}` 下创建主目录，sandbox 不是项目主目录
- sandbox bootstrap 必须同时冻结 brain runtime version 与 project payload package
- workflow 适用范围与非适用范围
- research / benchmark 作为 planning 前置步骤
- timeline / log bundles / delivery_report / release_report / audit_input_bundle
- task 督办、定时检查与升级责任链
- brain infra / sandbox / test / production 的环境基线
- 统一字段 schema
- project/task/sandbox/report/event 的命名规范
- 中心化 config/service registry 与 prompt 约束
- brain manager 的 workflow package 发布/校验/上提控制
- intake 和 bootstrap 的正式 pass/fail gate

## 预期落地顺序

1. 统一状态模型
2. 引入 project orchestrator 与 sandbox bootstrap
3. 引入 global sync 协议
4. 引入 release workflow
5. 引入 audit workflow
6. 将反馈闭环接入 knowledge / evolution
