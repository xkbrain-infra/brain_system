# Spec / LEP / Hooks 覆盖统计

> 自动生成 by `build.sh stats` · 2026-02-21T09:38:23Z

## 摘要

| 指标                  | 数值          |
|---------------------|-------------|
| Spec 文档总数           | 70          |
| LEP gates 总数        | 32          |
| LEP universal gates | 13          |
| Hooks 覆盖 gates      | 24/32 (75%) |

## Spec 文档（按分类）

### CORE（3）

| ID                   | Rule                                             | 路径                                  |
|----------------------|--------------------------------------------------|-------------------------------------|
| G-SPEC-CORE-LAYERS   | 四层架构定义（base/groups/infrastructure/runtime）- 全员必读 | /brain/base/spec/core/layers.yaml   |
| G-SPEC-CORE-LEP      | LEP 门控索引 - universal_gates(13) + domain_gates 引用 | /brain/base/spec/core/lep.yaml      |
| G-SPEC-CORE-WORKFLOW | 全员任务执行规范 - TaskID/Plan/验证/记录                     | /brain/base/spec/core/workflow.yaml |

### POLICY（46）

| ID                                    | Rule                                                                | 路径                                                                 |
|---------------------------------------|---------------------------------------------------------------------|--------------------------------------------------------------------|
| G-SPEC-POLICY-AGENT-PROTOCOL          | Agent 协作协议                                                          | /brain/base/spec/policies/agents/agent_protocol.yaml               |
| G-SPEC-POLICY-AGENTS-REGISTRY-SPEC    | agents_registry.yaml 结构规范                                           | /brain/base/spec/policies/agents/agents_registry_spec.yaml         |
| G-SPEC-POLICY-CONFIG-MANAGEMENT       | 双层配置管理规范                                                            | /brain/base/spec/policies/config/config_management.yaml            |
| G-SPEC-POLICY-ESTIMATION-TEMPLATE     | 时间估算模板                                                              | /brain/base/spec/policies/estimation/time_estimation_template.yaml |
| G-SPEC-POLICY-GROUP                   | Group 空间创建规范                                                        | /brain/base/spec/policies/creation/group.yaml                      |
| G-SPEC-POLICY-IPC-MESSAGE-FORMAT      | IPC 消息格式规范 - 前缀/结构/Telegram 同步                                      | /brain/base/spec/policies/ipc/message_format.yaml                  |
| G-SPEC-POLICY-IPC-PRIORITY            | IPC 消息优先级规范                                                         | /brain/base/spec/policies/ipc/priority.yaml                        |
| G-SPEC-POLICY-IPC-RELIABILITY-DESIGN  | IPC 可靠性设计                                                           | /brain/base/spec/policies/ipc/reliability_design.yaml              |
| G-SPEC-POLICY-LEP-AGENT-LIFECYCLE     | LEP Gate: Agent Lifecycle via Orchestrator Only - priority CRITICAL | /brain/base/spec/policies/lep/agent_lifecycle.yaml                 |
| G-SPEC-POLICY-LEP-APPROVAL-DELEGATION | LEP Gate: Approval Delegation to PMO - priority MEDIUM              | /brain/base/spec/policies/lep/approval_delegation.yaml             |
| G-SPEC-POLICY-LEP-ATOMIC              | LEP Gate: Atomic Plan - priority HIGH                               | /brain/base/spec/policies/lep/atomic.yaml                          |
| G-SPEC-POLICY-LEP-AUDIT               | LEP Gate: Audit Trail - priority LOW                                | /brain/base/spec/policies/lep/audit.yaml                           |
| G-SPEC-POLICY-LEP-BATCH-PARTIAL       | LEP Gate: Batch Partial Failure - priority MEDIUM                   | /brain/base/spec/policies/lep/batch_partial.yaml                   |
| G-SPEC-POLICY-LEP-CODE-STYLE          | LEP Gate: Code Style - priority LOW                                 | /brain/base/spec/policies/lep/code_style.yaml                      |
| G-SPEC-POLICY-LEP-DB-BACKUP           | LEP Gate: Database Backup First - priority CRITICAL                 | /brain/base/spec/policies/lep/db_backup.yaml                       |
| G-SPEC-POLICY-LEP-DB-MIGRATION        | LEP Gate: Database Migration Parallel - priority HIGH               | /brain/base/spec/policies/lep/db_migration.yaml                    |
| G-SPEC-POLICY-LEP-DEFER               | LEP Gate: Deferred Task Handoff - priority MEDIUM                   | /brain/base/spec/policies/lep/defer.yaml                           |
| G-SPEC-POLICY-LEP-DELETE-BACKUP       | LEP Gate: Delete with Backup - priority MEDIUM                      | /brain/base/spec/policies/lep/delete_backup.yaml                   |
| G-SPEC-POLICY-LEP-DOCKER-STD          | LEP Gate: Docker Standard Compliance - priority MEDIUM              | /brain/base/spec/policies/lep/docker_std.yaml                      |
| G-SPEC-POLICY-LEP-FILE-HIERARCHY      | LEP Gate: Global File Hierarchy Enforcement - priority HIGH         | /brain/base/spec/policies/lep/file_hierarchy.yaml                  |
| G-SPEC-POLICY-LEP-FILE-ORG            | LEP Gate: File Organization Standard - priority MEDIUM              | /brain/base/spec/policies/lep/file_org.yaml                        |
| G-SPEC-POLICY-LEP-INDEX               | LEP Gates 实现文件索引                                                    | /brain/base/spec/policies/lep/index.yaml                           |
| G-SPEC-POLICY-LEP-IPC-TARGET          | LEP Gate: IPC Target Validation - priority CRITICAL                 | /brain/base/spec/policies/lep/ipc_target.yaml                      |
| G-SPEC-POLICY-LEP-KVCACHE-FIRST       | LEP Gate: Query Registry Before Read/Write - priority HIGH          | /brain/base/spec/policies/lep/kvcache_first.yaml                   |
| G-SPEC-POLICY-LEP-MEMORY-PERSIST      | LEP Gate: Memory Persistence on Agent Start - priority HIGH         | /brain/base/spec/policies/lep/memory_persist.yaml                  |
| G-SPEC-POLICY-LEP-MEMORY-TIMELINE     | LEP Gate: Timeline Integrity - priority HIGH                        | /brain/base/spec/policies/lep/memory_timeline.yaml                 |
| G-SPEC-POLICY-LEP-NAWP                | LEP Gate: No Action Without Plan - priority CRITICAL                | /brain/base/spec/policies/lep/nawp.yaml                            |
| G-SPEC-POLICY-LEP-NONBLOCKING-CMDS    | LEP Gate: Non-blocking Runtime Commands - priority HIGH             | /brain/base/spec/policies/lep/nonblocking_cmds.yaml                |
| G-SPEC-POLICY-LEP-PATH-DISCIPLINE     | LEP Gate: Structured Path and Naming - priority MEDIUM              | /brain/base/spec/policies/lep/path_discipline.yaml                 |
| G-SPEC-POLICY-LEP-PROJECT-REF         | LEP Gate: Project Dual Reference - priority LOW                     | /brain/base/spec/policies/lep/project_ref.yaml                     |
| G-SPEC-POLICY-LEP-ROLLBACK-READY      | LEP Gate: Rollback-Ready Modification - priority CRITICAL           | /brain/base/spec/policies/lep/rollback_ready.yaml                  |
| G-SPEC-POLICY-LEP-SCOP                | LEP Gate: Scope Locking - priority CRITICAL                         | /brain/base/spec/policies/lep/scop.yaml                            |
| G-SPEC-POLICY-LEP-SCOPE-DEVIATION     | LEP Gate: No Silent Scope Reduction - priority HIGH                 | /brain/base/spec/policies/lep/scope_deviation.yaml                 |
| G-SPEC-POLICY-LEP-SPEC-LOCATION       | LEP Gate: SPEC Location Enforcement - priority CRITICAL             | /brain/base/spec/policies/lep/spec_location.yaml                   |
| G-SPEC-POLICY-LEP-SPEC-SYNC           | LEP Gate: Spec Synchronization - priority MEDIUM                    | /brain/base/spec/policies/lep/spec_sync.yaml                       |
| G-SPEC-POLICY-LEP-TECH-STACK          | LEP Gate: Technology Stack Enforcement - priority MEDIUM            | /brain/base/spec/policies/lep/tech_stack.yaml                      |
| G-SPEC-POLICY-LEP-TOOL-CONVENTIONS    | LEP Gate: Tool & Command Usage Conventions - priority CRITICAL      | /brain/base/spec/policies/lep/tool_conventions.yaml                |
| G-SPEC-POLICY-LEP-UNRECOVERABLE       | LEP Gate: Halt on Unrecoverable Error - priority CRITICAL           | /brain/base/spec/policies/lep/unrecoverable.yaml                   |
| G-SPEC-POLICY-LEP-USERSPACE           | LEP Gate: Userspace Separation - priority LOW                       | /brain/base/spec/policies/lep/userspace.yaml                       |
| G-SPEC-POLICY-LEP-VERIFICATION        | LEP Gate: Code Verification - priority HIGH                         | /brain/base/spec/policies/lep/verification.yaml                    |
| G-SPEC-POLICY-LEP-VERSION-UPGRADE     | LEP Gate: Version Upgrade Protocol - priority HIGH                  | /brain/base/spec/policies/lep/version_upgrade.yaml                 |
| G-SPEC-POLICY-MEMORY-PERSISTENCE      | Agent 会话记录持久化规范 - pipe-pane 捕获 stdout                               | /brain/base/spec/policies/memory/persistence.yaml                  |
| G-SPEC-POLICY-PROJECT                 | Project 空间创建规范                                                      | /brain/base/spec/policies/creation/project.yaml                    |
| G-SPEC-POLICY-PROJECT-CREATION        | 项目创建快速参考                                                            | /brain/base/spec/policies/creation/project_creation.yaml           |
| G-SPEC-POLICY-SECRETS-MANAGEMENT      | 敏感数据管理规范                                                            | /brain/base/spec/policies/secrets/secrets_management.yaml          |
| G-SPEC-POLICY-VALIDATORS              | LEP Validators 定义                                                   | /brain/base/spec/policies/lep/validators.yaml                      |

### STANDARD（11）

| ID                                         | Rule                                       | 路径                                                                    |
|--------------------------------------------|--------------------------------------------|-----------------------------------------------------------------------|
| G-SPEC-STANDARD-AGENT-ABILITIES-BUILD      | 构建系统规范：目录结构、build targets、流水线顺序、输出格式、列命名规则 | /brain/base/spec/standards/infra/agent_abilities_build.yaml           |
| G-SPEC-STANDARD-CPP                        | C++ 编码标准                                   | /brain/base/spec/standards/coding/cpp.yaml                            |
| G-SPEC-STANDARD-DEPLOYMENT                 | 部署规范                                       | /brain/base/spec/standards/infra/docker/deployment.yaml               |
| G-SPEC-STANDARD-DOCKER                     | Docker 规范                                  | /brain/base/spec/standards/infra/docker/docker.yaml                   |
| G-SPEC-STANDARD-FILE-ORGANIZATION          | 文件组织规范                                     | /brain/base/spec/standards/organization/file_organization.yaml        |
| G-SPEC-STANDARD-FILE-ORGANIZATION-EXAMPLES | 文件组织规范使用示例                                 | /brain/base/spec/standards/organization/file_organization_examples.md |
| G-SPEC-STANDARD-OPERATION                  | 数据库操作规范                                    | /brain/base/spec/standards/infra/database/operation.yaml              |
| G-SPEC-STANDARD-PROBLEM-SOLVING            | 问题解决工作流                                    | /brain/base/spec/standards/workflow/problem_solving.yaml              |
| G-SPEC-STANDARD-TIME-ESTIMATION            | Agent 工作时间估算标准（从 core 移入）                  | /brain/base/spec/standards/workflow/time_estimation.yaml              |
| G-SPEC-STANDARD-VERIFICATION               | 代码验证标准                                     | /brain/base/spec/standards/workflow/verification.yaml                 |
| G-SPEC-STANDARD-VERSION-UPGRADE            | 版本化升级规范                                    | /brain/base/spec/standards/workflow/version_upgrade.yaml              |

### TEMPLATE（10）

| ID                            | Rule                 | 路径                                                    |
|-------------------------------|----------------------|-------------------------------------------------------|
| G-SPEC-TEMPLATE-ARCHITECT     | Architect 角色模板       | /brain/base/spec/templates/agent/roles/architect.md   |
| G-SPEC-TEMPLATE-BASE-TEMPLATE | Agent CLAUDE.md 基础模板 | /brain/base/spec/templates/agent/base_template.md     |
| G-SPEC-TEMPLATE-DEVELOPER     | Developer 角色模板       | /brain/base/spec/templates/agent/roles/developer.md   |
| G-SPEC-TEMPLATE-DEVOPS        | DevOps 角色模板          | /brain/base/spec/templates/agent/roles/devops.md      |
| G-SPEC-TEMPLATE-FRONTDESK     | Frontdesk 角色模板       | /brain/base/spec/templates/agent/roles/frontdesk.md   |
| G-SPEC-TEMPLATE-PMO           | PMO 角色模板             | /brain/base/spec/templates/agent/roles/pmo.md         |
| G-SPEC-TEMPLATE-QA            | QA 角色模板              | /brain/base/spec/templates/agent/roles/qa.md          |
| G-SPEC-TEMPLATE-RESEARCHER    | Researcher 角色模板      | /brain/base/spec/templates/agent/roles/researcher.md  |
| G-SPEC-TEMPLATE-SPEC-DSL      | Spec 流程 DSL 模板       | /brain/base/spec/templates/spec/spec_dsl.yaml         |
| G-SPEC-TEMPLATE-UI-DESIGNER   | UI Designer 角色模板     | /brain/base/spec/templates/agent/roles/ui-designer.md |

## LEP Gates（按分类）

### GOVERNANCE（12）

| Gate ID                | Rule                                                             | Universal | 路径                                |
|------------------------|------------------------------------------------------------------|-----------|-----------------------------------|
| G-GATE-AUDIT           | 所有操作记录到 JSONL 日志                                                 |           | policies/lep/audit.yaml           |
| G-GATE-FILE-HIERARCHY  | 全局文件落盘必须遵循四域层级与组织规范，禁止路径散落                                       | ✓         | policies/lep/file_hierarchy.yaml  |
| G-GATE-FILE-ORG        | 所有新文件创建必须遵循文件组织规范，避免文件直接堆积在顶级或项目根目录。                             |           | policies/lep/file_org.yaml        |
| G-GATE-IPC-TARGET      | 发送 IPC 消息前必须确认目标 agent 存在：                                       | ✓         | policies/lep/ipc_target.yaml      |
| G-GATE-KVCACHE-FIRST   | 必须优先使用索引系统（registry.yaml）查找文档，禁止盲目搜索。                            | ✓         | policies/lep/kvcache_first.yaml   |
| G-GATE-MEMORY-PERSIST  | agentctl 启动 agent 后必须配置 tmux pipe-pane 写入 /xkagent_infra/runtime/memory/ |           | policies/lep/memory_persist.yaml  |
| G-GATE-MEMORY-TIMELINE | timeline.md 只追加，永不覆盖                                             |           | policies/lep/memory_timeline.yaml |
| G-GATE-PATH-DISCIPLINE | 文件必须归属正确层级，文件名必须体现所属模块                                           | ✓         | policies/lep/path_discipline.yaml |
| G-GATE-PROJECT-REF     | 子项目必须有 parent ref                                                |           | policies/lep/project_ref.yaml     |
| G-GATE-SPEC-LOCATION   | SPEC 文件必须在指定目录，避免分散存储                                            |           | policies/lep/spec_location.yaml   |
| G-GATE-SPEC-SYNC       | 项目代码改动后必须同步更新对应 spec (index、路径、状态等)                              |           | policies/lep/spec_sync.yaml       |
| G-GATE-USERSPACE       | 用户内容 → userspace/，Agent 整理后 → spec/                              |           | policies/lep/userspace.yaml       |

### OPERATION（5）

| Gate ID               | Rule                          | Universal | 路径                               |
|-----------------------|-------------------------------|-----------|----------------------------------|
| G-GATE-DB-BACKUP      | 数据库操作前必须先备份                   |           | policies/lep/db_backup.yaml      |
| G-GATE-DB-MIGRATION   | 数据库迁移必须新老并存，不直接替换             |           | policies/lep/db_migration.yaml   |
| G-GATE-DELETE-BACKUP  | 删除前必须先备份                      | ✓         | policies/lep/delete_backup.yaml  |
| G-GATE-DOCKER-STD     | - WORKDIR /app                |           | policies/lep/docker_std.yaml     |
| G-GATE-ROLLBACK-READY | 修改任何文件前，必须确保可回滚。根据文件类型选择对应策略： | ✓         | policies/lep/rollback_ready.yaml |

### PROCESS（5）

| Gate ID                    | Rule                                               | Universal | 路径   O                                 |
|----------------------------|----------------------------------------------------|-----------|---------------------------------------|
| G-GATE-APPROVAL-DELEGATION | Agent 需要审批时，不直接等待用户，而是发送 APPROVAL_REQUEST 给组内 PMO。 |           | policies/lep/approval_delegation.yaml |
| G-GATE-ATOMIC              | Plan 必须原子化（具体到文件/行号/动作）                            | ✓         | policies/lep/atomic.yaml              |
| G-GATE-DEFER               | Agent 产生"当前不做、以后要做"的延迟任务时，必须通过 IPC 通知对应 PMO：       |           | policies/lep/defer.yaml               |
| G-GATE-NAWP                | 修改操作需要 Plan + PMO 批准                               | ✓         | policies/lep/nawp.yaml                |
| G-GATE-SCOPE-DEVIATION     | 禁止静默缩减执行范围，偏差必须通知 PMO                              | ✓         | policies/lep/scope_deviation.yaml     |

### QUALITY（8）

| Gate ID                 | Rule                                                           | Universal | 路径                                 |
|-------------------------|----------------------------------------------------------------|-----------|------------------------------------|
| G-GATE-BATCH-PARTIAL    | 批量操作部分失败时记录并通知 PMO                                             |           | policies/lep/batch_partial.yaml    |
| G-GATE-CODE-STYLE       | 代码遵循项目规范                                                       |           | policies/lep/code_style.yaml       |
| G-GATE-NONBLOCKING-CMDS | - 禁止使用 `docker exec ... cat /proc/*/fd/*` 抓日志（可能无限阻塞/卡死 Agent） | ✓         | policies/lep/nonblocking_cmds.yaml |
| G-GATE-TECH-STACK       | 操作必须符合项目 spec/constraints.yaml 中声明的技术栈                         |           | policies/lep/tech_stack.yaml       |
| G-GATE-TOOL-CONVENTIONS | 强制执行工具和命令的使用规范：                                                |           | policies/lep/tool_conventions.yaml |
| G-GATE-UNRECOVERABLE    | 不可恢复错误立即停止                                                     | ✓         | policies/lep/unrecoverable.yaml    |
| G-GATE-VERIFICATION     | 代码必须编译通过 + 测试通过                                                | ✓         | policies/lep/verification.yaml     |
| G-GATE-VERSION-UPGRADE  | 升级必须版本化，保留回退方案                                                 |           | policies/lep/version_upgrade.yaml  |

### SECURITY（2）

| Gate ID                | Rule                                      | Universal | 路径                                |
|------------------------|-------------------------------------------|-----------|-----------------------------------|
| G-GATE-AGENT-LIFECYCLE | 所有 Agent 生命周期操作必须且只能通过 brain-agentctl 执行： |           | policies/lep/agent_lifecycle.yaml |
| G-GATE-SCOP            | 操作必须在允许的路径内                               | ✓         | policies/lep/scop.yaml            |

## Hooks 覆盖（24/32 = 75%）

### 已覆盖（24）

| Gate ID                 | Method         | Universal | 路径                                 |
|-------------------------|----------------|-----------|------------------------------------|
| G-GATE-AGENT-LIFECYCLE  | python_inline  |           | policies/lep/agent_lifecycle.yaml  |
| G-GATE-AUDIT            | python_logger  |           | policies/lep/audit.yaml            |
| G-GATE-BATCH-PARTIAL    | python_inline  |           | policies/lep/batch_partial.yaml    |
| G-GATE-DB-BACKUP        | python_inline  |           | policies/lep/db_backup.yaml        |
| G-GATE-DB-MIGRATION     | python_inline  |           | policies/lep/db_migration.yaml     |
| G-GATE-DELETE-BACKUP    | python_inline  | ✓         | policies/lep/delete_backup.yaml    |
| G-GATE-DOCKER-STD       | python_inline  |           | policies/lep/docker_std.yaml       |
| G-GATE-FILE-HIERARCHY   | python_checker | ✓         | policies/lep/file_hierarchy.yaml   |
| G-GATE-FILE-ORG         | python_checker |           | policies/lep/file_org.yaml         |
| G-GATE-KVCACHE-FIRST    | python_inline  | ✓         | policies/lep/kvcache_first.yaml    |
| G-GATE-MEMORY-TIMELINE  | python_inline  |           | policies/lep/memory_timeline.yaml  |
| G-GATE-NONBLOCKING-CMDS | python_inline  | ✓         | policies/lep/nonblocking_cmds.yaml |
| G-GATE-PATH-DISCIPLINE  | python_checker | ✓         | policies/lep/path_discipline.yaml  |
| G-GATE-PROJECT-REF      | python_inline  |           | policies/lep/project_ref.yaml      |
| G-GATE-ROLLBACK-READY   | python_inline  | ✓         | policies/lep/rollback_ready.yaml   |
| G-GATE-SCOP             | c_binary       | ✓         | policies/lep/scop.yaml             |
| G-GATE-SCOPE-DEVIATION  | python_inline  | ✓         | policies/lep/scope_deviation.yaml  |
| G-GATE-SPEC-LOCATION    | python_checker |           | policies/lep/spec_location.yaml    |
| G-GATE-SPEC-SYNC        | python_inline  |           | policies/lep/spec_sync.yaml        |
| G-GATE-TECH-STACK       | python_inline  |           | policies/lep/tech_stack.yaml       |
| G-GATE-TOOL-CONVENTIONS | python_inline  |           | policies/lep/tool_conventions.yaml |
| G-GATE-UNRECOVERABLE    | python_inline  | ✓         | policies/lep/unrecoverable.yaml    |
| G-GATE-USERSPACE        | python_inline  |           | policies/lep/userspace.yaml        |
| G-GATE-VERSION-UPGRADE  | python_inline  |           | policies/lep/version_upgrade.yaml  |

### 未覆盖（8）

| Gate ID                    | 原因/Method                  | Universal | 路径                                                |
|----------------------------|----------------------------|-----------|---------------------------------------------------|
| G-GATE-APPROVAL-DELEGATION | message_routing_validation |           | policies/lep/approval_delegation.yaml             |
| G-GATE-ATOMIC              | plan_validator             | ✓         | policies/lep/atomic.yaml                          |
| G-GATE-CODE-STYLE          | linter                     |           | policies/lep/code_style.yaml                      |
| G-GATE-DEFER               | message_content_validation |           | policies/lep/defer.yaml                           |
| G-GATE-IPC-TARGET          | daemon_validation          | ✓         | policies/lep/ipc_target.yaml                      |
| G-GATE-MEMORY-PERSIST      | 无 enforcement              |           | /brain/base/spec/policies/memory/persistence.yaml |
| G-GATE-NAWP                | plan_mode_check            | ✓         | policies/lep/nawp.yaml                            |
| G-GATE-VERIFICATION        | test_runner                | ✓         | policies/lep/verification.yaml                    |
