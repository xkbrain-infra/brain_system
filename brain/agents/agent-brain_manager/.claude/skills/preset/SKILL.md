---
id: G-SKILL-PRESET
name: preset
description: "每次对话开始时强制调用，完成工作空间路由、Sandbox 评估与项目初始化。当用户提出任何需要创建/修改文件、编写代码、进行项目性工作的请求时，必须先运行此 skill。"
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Edit, Bash, Glob
argument-hint: "[new|resume] [group/project] [--sandbox=auto|read_only|worktree_sandbox|full_sandbox]"
metadata:
  status: active
  source_project: /xkagent_infra/groups/brain/projects/base
  publish_target: /xkagent_infra/brain/base/skill/preset
  version: "2.0.0"
  changelog: "新增 Sandbox 模式评估与初始化集成"
---

# /preset — 会话路由、Sandbox 评估与项目初始化

每次对话开始，在任何文件操作之前，必须先运行此 skill 确定工作空间。

## 根目录

`/xkagent_infra/groups/`

## 执行流程

### Step 1 — 判断新建 or 已有

从对话上下文推断，或直接问用户：

> 这次是新项目，还是继续一个已有项目？

- 已有项目 → 跳到 [进入已有项目](#进入已有项目)
- 新项目 → 跳到 [路由新项目](#路由新项目)

---

### 路由新项目

1. **扫描现有 groups**（动态读取）：
   ```bash
   ls /xkagent_infra/groups/
   ```

2. **根据对话内容推断归属 group**：
   - 与已有 group 明显相关 → 建议该 group
   - 不确定或跨领域 → 默认 `drafts`

3. **向用户确认**（第一阶段 - 基础信息）：
   ```
   Group   : <group-name>
   Project : <project-name>    # kebab-case
   Path    : /xkagent_infra/groups/<group>/projects/<project>
   ```
   等待确认或修改。

4. **Sandbox 模式评估**（第二阶段 - 关键新增）：

   读取用户输入或命令行参数 `--sandbox`：
   - `--sandbox=read_only` → 直接选择 Level 3
   - `--sandbox=worktree_sandbox` → 直接选择 Level 2
   - `--sandbox=full_sandbox` → 直接选择 Level 1
   - `--sandbox=auto` 或未指定 → 执行自动评估

   **自动评估流程**（参考 `/brain/base/workflow/project_delivery/workflow/sandbox_evaluation.yaml`）：

   ```yaml
   评估问题序列:
     - question: "项目是否需要写入文件？"
       if: "否"
       then: "推荐 read_only (Level 3)"
       confidence: high

     - question: "项目是否仅需在项目目录内写入文件？"
       if: "是"
       then: "推荐 worktree_sandbox (Level 2)"
       confidence: high

     - question: "项目是否需要以下任一条件？"
       conditions:
         - "Docker / 容器化环境"
         - "数据库服务 (PostgreSQL, MySQL, Redis)"
         - "消息队列 (RabbitMQ, Kafka)"
         - "特定语言 runtime 版本"
         - "编译工具链"
         - "修改系统配置"
         - "可能污染 Brain 环境"
        - "涉及 /brain/infrastructure/** 核心服务（如 brain_dashboard、agent_gateway、task_manager 等）"
        - "涉及 /brain/base/** 核心规范（spec、hooks、knowledge、skill、workflow）"
        - "修改会影响其他 brain 服务运行（共享服务依赖、IPC 通信、全局配置）"
       if: "任一条件为是"
       then: "推荐 full_sandbox (Level 1)"
       confidence: high
      note: |
        brain 核心基础设施项目必须使用 full_sandbox：
        - brain_dashboard：涉及多个 brain 服务，需要完整隔离
        - agent_gateway、task_manager 等核心服务：影响全局运行
        - base 域修改（spec/hooks/skill）：风险等级为 critical，需完全隔离

     - question: "项目复杂度如何？"
       options:
         - "简单脚本/配置 (< 4小时)" → "read_only 或 worktree_sandbox"
         - "单模块功能 (2-5天)" → "worktree_sandbox"
         - "多服务/架构设计 (> 1周)" → "full_sandbox"
   ```

5. **Sandbox 模式确认**：
   ```
   ============================================
   🛡️ Sandbox 模式评估结果
   ============================================
   推荐模式: <sandbox_mode>
   置信度  : <high|medium|low>

   模式说明:
   - read_only: 只读分析，无文件写入权限
   - worktree_sandbox: 项目目录内读写，受 hooks 保护
   - full_sandbox: 完整容器隔离，独立环境

   确认使用此模式？[Y/n/变更模式]
   ============================================
   ```

6. **根据 Sandbox 模式创建项目结构**：

   **Level 3 (read_only)**:
   ```bash
   mkdir -p /xkagent_infra/groups/<group>/projects/<project>/analysis
   # 激活 read_only hooks
   ```

   **Level 2 (worktree_sandbox)**:
   ```bash
   # 创建 git worktree
   cd /xkagent_infra/groups/<group>/projects/
   git worktree add <project> <branch>
   mkdir -p <project>/userspace
   mkdir -p <project>/specs
   # 激活 worktree_scope_guard hooks
   ```

   **Level 1 (full_sandbox)**:
   ```bash
   mkdir -p /xkagent_infra/groups/<group>/projects/<project>
   # 准备 Dockerfile / compose.yaml
   # 标记待 bootstrap
   ```

7. **写入项目元数据**（根据 sandbox 模式）：

   **README.md**:
   ```markdown
   # <project-name>

   - **Group**: <group>
   - **Created**: <YYYY-MM-DD HH:MM>
   - **Goal**: <一句话描述>
   - **Sandbox Mode**: <read_only|worktree_sandbox|full_sandbox>
   - **Evaluation Confidence**: <high|medium|low>
   ```

   **session.md**:
   ```markdown
   # Session

   - **Project**: <project-name>
   - **Group**: <group-name>
   - **Path**: /xkagent_infra/groups/<group>/projects/<project>
   - **Sandbox Mode**: <sandbox_mode>
   - **Started**: <YYYY-MM-DD HH:MM>
   - **Goal**: <一句话描述本次任务目标>
   ```

   **sandbox.yaml**（新增，Level 2/3 必需）：
   ```yaml
   sandbox:
     mode: <sandbox_mode>
     evaluated_at: <ISO8601>
     evaluated_by: preset_skill
     confidence: <high|medium|low>
     project_root: /xkagent_infra/groups/<group>/projects/<project>

     # Level 2 特有
     worktree:
       branch: <branch-name>
       base_commit: <commit-hash>

     # Level 1 特有
     container:
       image: <image-name>
       status: pending_bootstrap

     # 约束配置
     constraints:
       allowed_write_paths:
         - "${PROJECT_ROOT}/**"
       blocked_paths:
         - "/brain/**"
         - "/etc/**"
         - "/usr/**"

     # 升级追踪
     upgrade_history: []
   ```

8. **注册到 projects.yaml**（非 drafts group 且该文件存在时追加）

9. **激活对应 Hooks**（根据 sandbox 模式）：
   - Level 3: `read_only_guard` + `audit_logging`
   - Level 2: `worktree_scope_guard` + `audit_logging`
   - Level 1: 容器内 hooks（bootstrap 后配置）

---

### 进入已有项目

1. 扫描所有项目：
   ```bash
   ls /xkagent_infra/groups/*/projects/
   ```

2. 列出供用户选择（格式：`<group>/<project>`）

3. 读取项目元数据恢复上下文：
   - `README.md`
   - `session.md`
   - `sandbox.yaml`（读取 sandbox 模式，激活对应约束）

4. **Sandbox 模式验证**：
   - 检查 `sandbox.yaml` 中的 `mode`
   - 验证 hooks 是否激活
   - 如 mode=worktree_sandbox，验证 worktree 状态
   - 如 mode=full_sandbox，验证容器状态

5. **如需升级 Sandbox 模式**：
   - 参考 `/brain/base/workflow/project_delivery/workflow/sandbox_upgrade_escalation.yaml`
   - 记录升级原因到 `sandbox.yaml`
   - 执行升级流程（L3→L2 / L2→L1 / L3→L1）

---

### Sandbox 升级检测

在执行过程中，如果遇到以下情况，提示升级：

```yaml
触发升级建议的条件:
  read_only 模式:
    - 尝试使用 Write/Edit 工具 → 建议升级到 worktree_sandbox
    - 尝试执行写入命令 → 建议升级

  worktree_sandbox 模式:
    - 尝试写入 project_root 外 → 建议升级到 full_sandbox
    - 需要服务依赖 (db/redis) → 建议升级
    - build/test 失败（环境隔离不足）→ 建议升级

升级流程:
  1. 暂停当前任务
  2. 记录升级原因和已完成工作
  3. 创建升级 audit record
  4. 执行升级（创建 worktree / 启动 container）
  5. 迁移工作
  6. 恢复执行
```

---

## 声明工作空间（必须输出）

```
✅ 工作空间已就绪
   路径: /xkagent_infra/groups/<group>/projects/<project>
   目标: <goal>
   Sandbox: <sandbox_mode> [<confidence>]
```

后续文件操作：
- Level 3: 仅读取，输出到 console
- Level 2: 默认在 `userspace/` 下进行
- Level 1: 容器内执行，按 container 规范

## 规则

- project 名使用 kebab-case
- 禁止跳过确认步骤
- `drafts` 下的项目不注册到 `projects.yaml`
- 每个 project 必须有 `README.md`、`session.md` 和 `sandbox.yaml`
- **Sandbox 模式一旦选择，执行过程中不可降级**
- 升级必须记录 audit trail 到 `sandbox.yaml`

## 相关文档

- Sandbox 评估流程: `/brain/base/workflow/project_delivery/workflow/sandbox_evaluation.yaml`
- Sandbox 升级流程: `/brain/base/workflow/project_delivery/workflow/sandbox_upgrade_escalation.yaml`
- Sandbox 范围保护: `/brain/base/workflow/project_delivery/governance/sandbox_scope_guard.yaml`
