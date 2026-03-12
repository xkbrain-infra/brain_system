# 20260311 Multicore Workflow

## Summary

- 新增一套面向 `brain infra + sandbox + orchestrator` 的 workflow 设计方案
- 明确 `brain infra`、`project orchestrator`、`global task manager`、`release manager`、`audit orchestrator` 的职责边界
- 定义项目执行闭环所需的状态机、主 workflow、同步协议、观测与反馈机制
- 新增 logging service 设计，覆盖 timeline/task_progress/service_runtime/release/audit 分类日志、按项目组|项目落盘与跨层同步
- 新增 config registry service 设计，覆盖配置版本、端口申请、service 注册、supervisor 注册、发现与 prompt 约束
- 新增 config registry protocol，补齐 control IPC 中的配置/注册命令与 payload 契约
- 新增 config registration sequences，固化 bootstrap/runtime/release 阶段的注册顺序流
- 新增 brain manager runtime package 发布控制设计，覆盖校验、发布、归档与 promotion 到 base 的规则
- 新增最小上线顺序与运行拓扑设计，固定 foundation/execution_core/visibility/delivery 的 rollout 路径

## Scope

- 仅新增设计文档
- 不修改现有运行时代码
- 不变更现有 `/brain/base/workflow` SSOT
