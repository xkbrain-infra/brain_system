---
id: G-SKILL-PRESET
name: preset
description: "每次对话开始时强制调用，完成工作空间路由与项目初始化。当用户提出任何需要创建/修改文件、编写代码、进行项目性工作的请求时，必须先运行此 skill。"
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Edit, Bash, Glob
argument-hint: "[new|resume] [group/project]"
metadata:
  status: active
  source_project: /xkagent_infra/groups/brain/projects/base
  publish_target: /xkagent_infra/brain/base/skill/preset
---

# /preset — 会话路由与项目初始化

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

3. **向用户确认**：
   ```
   Group   : <group-name>
   Project : <project-name>    # kebab-case
   Path    : /xkagent_infra/groups/<group>/projects/<project>
   ```
   等待确认或修改。

4. **创建项目目录**：
   ```bash
   mkdir -p /xkagent_infra/groups/<group>/projects/<project>/userspace
   mkdir -p /xkagent_infra/groups/<group>/projects/<project>/specs
   ```

5. **写入 README.md**：
   ```markdown
   # <project-name>

   - **Group**: <group>
   - **Created**: <YYYY-MM-DD HH:MM>
   - **Goal**: <一句话描述>
   ```

6. **写入 session.md**：
   ```markdown
   # Session

   - **Project**: <project-name>
   - **Group**: <group-name>
   - **Path**: /xkagent_infra/groups/<group>/projects/<project>
   - **Started**: <YYYY-MM-DD HH:MM>
   - **Goal**: <一句话描述本次任务目标>
   ```

7. **注册到 projects.yaml**（非 drafts group 且该文件存在时追加）

---

### 进入已有项目

1. 扫描所有项目：
   ```bash
   ls /xkagent_infra/groups/*/projects/
   ```

2. 列出供用户选择（格式：`<group>/<project>`）

3. 读取项目 `README.md` 或 `session.md` 恢复上下文

---

## 声明工作空间（必须输出）

```
✅ 工作空间已就绪
   路径: /xkagent_infra/groups/<group>/projects/<project>
   目标: <goal>
```

后续文件操作默认在 `userspace/` 下进行。

## 规则

- project 名使用 kebab-case
- 禁止跳过确认步骤
- `drafts` 下的项目不注册到 `projects.yaml`
- 每个 project 必须有 `README.md` 和 `session.md`
