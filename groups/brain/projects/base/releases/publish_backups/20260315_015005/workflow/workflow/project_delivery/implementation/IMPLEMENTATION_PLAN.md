# Multicore Workflow Implementation Plan

## 目标

将 `multicore workflow` 从 runtime architecture proposal 推进到第一批可执行实现任务。

本阶段不要求一次完成全部重构，而是优先建立最小闭环：

1. 统一状态模型
2. 建立 `runtime/architecture/multicore` 发布包
3. 建立 `brain manager publish service`
4. 建立 `config registry service`
5. 建立 `project orchestrator` skeleton
6. 建立 `global sync` 协议与 task manager 对接
7. 引入 logging service
8. 引入 release gate
9. 引入 audit pipeline skeleton

## 实施原则

### 1. 先统一语义，再扩展执行器

当前文档态和实现态的最大问题是状态语义不一致。没有统一状态机，后续 orchestrator、watchdog、release、audit 都会反复返工。

### 2. 先建立 runtime package，再抽取到 base

先把 multicore 体系作为 runtime package 运转，确认稳定后再上提到 `base/workflow` 和 `base/spec`。

### 3. 先做最小可运行闭环，不先追求完美大一统

第一批实现目标是：

`project intake -> research -> sandbox bootstrap -> planning -> task modeling -> local execution -> global sync -> release candidate -> audit record`

而不是一次性完成所有高级治理能力。

## Phase 1: 状态模型与运行期发布结构

目标：

- 建立统一状态语义
- 为 multicore architecture package 提供正式 runtime 目录

交付：

- `runtime/architecture/multicore/index.yaml`
- `state_machines.yaml`
- 对现有 task manager / orchestrator / workflow 文档做状态映射表

完成标准：

- 对外只有一套 project/task/agent/release 状态名
- 至少存在旧实现状态到新状态的 compatibility mapping

## Phase 2: Brain Manager Publish and Config Registry

目标：

- 明确 runtime package 的发布控制者
- 让 sandbox bootstrap、service 注册、端口申请有统一控制面

交付：

- `brain manager publish service` 规则
- `runtime package publish flow`
- `config registry service`
- `config/service/supervisor/port` schema 与控制面协议

完成标准：

- brain manager 仅按 `MANIFEST/index` 发布，不猜目录
- sandbox/service 可通过统一协议申请 config、port、supervisor registration

## Phase 3: Project Orchestrator Skeleton

目标：

- 区分当前 `agentctl orchestrator` 与新的 `project orchestrator`
- 新 orchestrator 只负责项目执行编排

交付：

- `project orchestrator` 服务骨架
- intake 后可创建 project runtime root
- 可接收 `PROJECT_CREATE` / `TASK_ASSIGN` / `TASK_DONE` / `PROJECT_SNAPSHOT`

完成标准：

- 可以注册到 global task manager
- 可以推进 project 从 `BOOTSTRAPPING -> PLANNING`
- 可以在 `PLANNING -> TASK_MODELING -> EXECUTING` 链路上完成最小闭环推进

## Phase 4: Global Sync、Logging 与观测

目标：

- manager 能看到每个 sandbox 的项目状态
- heartbeat / snapshot / watchdog 能发现卡死和漏推进

交付：

- control IPC 协议落地
- project snapshot registry
- heartbeat registry
- logging service contract 与本地/全局日志布局
- watchdog 初版

完成标准：

- orchestrator 定时上报 project snapshot
- agent / orchestrator heartbeat 可被查询
- 关键 timeline/task_progress/service logs 可落盘并上卷摘要
- watchdog 能识别 offline/stale/stuck 三类问题

## Phase 5: Release Skeleton

目标：

- 项目完成后不直接结束，而是显式进入 release gate

交付：

- release candidate registry
- stage/prod gate 状态流转
- rollback 记录结构

完成标准：

- 项目完成后可进入 `RELEASE_READY`
- release manager 能记录 `BUILD_READY -> TESTED -> ... -> RELEASED`

## Phase 6: Audit Skeleton

目标：

- 项目结束后有标准审计入口

交付：

- audit record schema
- findings / root cause / improvement action 基础结构
- feedback routing 初版

完成标准：

- `RELEASED` 或 `FAILED` 后自动创建 audit record
- audit 结果可路由到 knowledge/workflow/spec/evolution

## 风险

- 状态机命名不统一会拖慢全部后续工作
- 旧 orchestrator 名称与新 project orchestrator 容易冲突
- global task manager 如果直接吞掉项目内细节，会重新变成大单体

## 建议的第一批实现顺序

1. 补运行期 package 目录与索引
2. 补状态映射表
3. 补 brain manager publish service
4. 补 config registry service
5. 新建 project orchestrator skeleton
6. 接 global task manager project snapshot
7. 接 timer service
8. 接 logging service
9. 接 heartbeat/watchdog
10. 接 release record
11. 接 audit record
