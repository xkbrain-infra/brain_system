---
name: brain-publish-core
description: "当任务涉及 whole-brain core 发布时使用。它不是单独的 base publish，而是编排 brain/base、brain/platform、brain/bin、brain root runtime assets、brain/agents 与 core infrastructure services 的统一发布入口。"
publish_target: /xkagent_infra/brain/base/skill/brain-publish-core
---

# brain-publish-core

## 适用范围

| 场景 | 处理方式 |
| --- | --- |
| 只发布 `groups/brain/projects/base -> brain/base` | 使用 `/brain-publish` 或 `publish_base.sh` |
| 需要 whole-brain core 发布 | 使用本 skill |
| 只发布某个 infrastructure service | 直接走对应项目 Makefile |
| 需要生成发布清单、依赖清单、验证报告 | 使用本 skill |

## 核心原则

- `core publish` 对应整个 `/brain` 运行面，不是只有 `brain/base`
- `publish_base.sh` 只是子步骤
- `infrastructure` 发布必须带路由矩阵，明确是否影响 supervisor / registry / skill / mcp / hooks / `/brain/bin`
- 每次发布必须产出 manifest / dependency BOM / change summary / verification report

## 入口

- 脚本：`/xkagent_infra/groups/brain/projects/base/scripts/publish_core.sh`
- manifest：`/xkagent_infra/groups/brain/projects/base/config/core_publish_manifest.yaml`
- infrastructure routing：`/xkagent_infra/groups/brain/projects/base/config/infrastructure_publish_routing.yaml`
- policy：`/xkagent_infra/groups/brain/projects/base/spec/policies/deployment/core_publish.yaml`

## 标准 SOP

### 1. 先做 dry-run

```bash
bash /xkagent_infra/groups/brain/projects/base/scripts/publish_core.sh --dry-run --scope all
```

检查产物目录：

```bash
ls -1dt /xkagent_infra/groups/brain/projects/base/releases/core_publish/* | head
```

必须审阅：

- `resolved_core_publish_manifest.yaml`
- `resolved_infrastructure_publish_routing.yaml`
- `core_dependency_manifest.yaml`
- `change_summary.md`
- `verification_report.yaml`

### 2. 判断是否存在 blocking gap

关注两类问题：

- `manual_gap`
  说明某个 core member 还没有统一 Makefile / register flow，正式发布默认会阻断
- `verification warnings`
  说明 `/brain/bin`、`/brain/.claude/.codex/.gemini`、`brain/agents` 或 infra target 有缺口

### 3. 正式发布

无 blocking gap 时：

```bash
bash /xkagent_infra/groups/brain/projects/base/scripts/publish_core.sh --publish --scope all
```

只发布某个 phase：

```bash
bash /xkagent_infra/groups/brain/projects/base/scripts/publish_core.sh --publish --scope foundation
```

只发布单个 service：

```bash
bash /xkagent_infra/groups/brain/projects/base/scripts/publish_core.sh --publish --scope service:brain_task_manager
```

### 4. 发布后核对

至少核对：

- `/xkagent_infra/brain/base`
- `/xkagent_infra/brain/platform`
- `/xkagent_infra/brain/bin`
- `/xkagent_infra/brain/.claude`
- `/xkagent_infra/brain/.codex`
- `/xkagent_infra/brain/.gemini`
- `/xkagent_infra/brain/agents/*/.brain`
- `/xkagent_infra/brain/agents/*/.claude`

以及本次 reports 里的：

- `activation_report.yaml`
- `verification_report.yaml`

## 当前实现边界

- `brain/base` 已接入正式发布
- `brain/platform` 已接入目录镜像发布
- `brain/bin` / root runtime assets / agents runtime assets 已纳入验证范围
- `infrastructure` 通过 routing matrix 统一建模
- 对于缺 Makefile 或缺 register flow 的 service，会在 dry-run 中明确报告 `manual_gap`
