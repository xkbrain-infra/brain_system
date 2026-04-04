---
id: G-SKILL-DEPLOY-BRAIN-PUBLISH
name: brain-publish
description: "当任务涉及整个 Brain 的内部发布链时使用：包括 base 域发布、infrastructure service 发布入口、runtime 配置刷新、或 pending 合并。它不负责整体 semver/tag 决策，也不直接负责 docker image artifact 构建。"
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Edit, Bash, Glob
argument-hint: "[base|infra|runtime|pending|root|skill|spec|hooks|knowledge|workflow|scripts|mcp|agents|all]"
metadata:
  status: active
  source_project: /xkagent_infra/groups/brain/projects/base
  publish_target: /xkagent_infra/brain/base/skill/brain-publish
  spec_ref: /brain/base/spec/policies/deployment/base_publish.yaml
---

# brain-publish

说明：
- `brain-publish` 是整个 Brain 的内部发布入口
- 它覆盖 `base`、`infrastructure service`、`runtime config`、`pending`
- `release` 和 `image` 仍由专门 skill 处理

## 触发场景

| 情境 | 跳转 |
|------|------|
| 修改了 `projects/base` 的 root files / skill / spec / hooks / knowledge / workflow / scripts / mcp | → [发布 base 域](#发布-base-域) |
| 修改了 `groups/brain/projects/infrastructure/<service>/` 下的服务源码或构建脚本 | → [发布 infrastructure 服务](#发布-infrastructure-服务) |
| 新增了一个 skill | → [新增 skill 完整流程](#新增-skill-完整流程) |
| 修改了 skill_bindings / lep_bindings / agents_registry | → [刷新 runtime 配置](#刷新-runtime-配置) |
| 有 pending 批次需要合并发布 | → [合并 pending 批次](#合并-pending-批次) |
| 整体版本号 / git tag / release notes | → 使用 `/brain-publish-release` |
| Docker 镜像构建 / push / digest 校验 | → 使用 `/brain-publish-image` |
| 不确定改动属于哪类 | → [判断变更类型](#判断变更类型) |

不适用：
- 直接修改 `/xkagent_infra/brain/base/`，发布态不是开发源
- 直接修改 `/xkagent_infra/brain/infrastructure/service/`，运行态不是开发源
- Brain 整体版本发布
- Docker image artifact 构建或推送

---

## 判断变更类型

1. 这是哪一类发布？
   - Type 1: Brain 内部改动进入运行态
     例：base domain / infrastructure service / runtime config / pending merge
     → 使用本 skill
   - Type 2: Brain 整体版本发布
     例：`brain 1.0.0`、git tag、release notes、版本同步
     → 使用 `/brain-publish-release`
   - Type 3: Brain image / docker artifact 发布
     例：`docker build`、`docker push`、镜像 digest / tag 校验
     → 使用 `/brain-publish-image`

2. Type 1 改动在哪里？
   - `groups/brain/projects/base/*` → 走 publish_base.sh
   - `groups/brain/projects/infrastructure/<service>/*` → 走该 service 的 Makefile / project.yaml / release_process
   - `brain/infrastructure/config/agentctl/*.yaml` → 走 agentctl，不走 publish_base.sh

3. Type 1 改动是什么？
   - root files 或 skill / spec / hooks / knowledge / workflow / scripts / mcp → [发布 base 域](#发布-base-域)
   - service 源码 / 二进制 / supervisor 注册 / releases 目录 → [发布 infrastructure 服务](#发布-infrastructure-服务)
   - skill_bindings / lep_bindings / agents_registry → [刷新 runtime 配置](#刷新-runtime-配置)
   - pending 批次合并 → [合并 pending 批次](#合并-pending-批次)

4. 是否同时新增了 skill？
   - 是 → [新增 skill 完整流程](#新增-skill-完整流程)

---

## 发布 base 域

> 深入规则：`spec_ref § base_publish.domain_notes`

```bash
PUBLISH_BASE=/xkagent_infra/brain/base/scripts/publish_base.sh

# 1. dry-run 确认
$PUBLISH_BASE --dry-run --domain <domain>

# 2. 正式发布
$PUBLISH_BASE --publish --domain <domain>
```

`<domain>` 可选值：`root` `skill` `spec` `hooks` `knowledge` `workflow` `scripts` `mcp` `evolution` `agents` `all`

约束：
- 必须先 dry-run，确认输出无误再 publish
- 用户入口固定使用 `/xkagent_infra/brain/base/scripts/publish_base.sh`
- `publish_base.sh` 内部回退到 `/xkagent_infra/groups/brain/projects/base` 作为 `source_root`，这是预期行为
- `--domain root` 用于同步 `brain/base` 根文件
- `--domain all` 包含 agents 域，会同时分发 skill 到所有 agent
- `--domain mcp` 会额外刷新 `/brain/bin/mcp/mcp-brain_ipc_c`

---

## 发布 infrastructure 服务

> 深入规则：`/xkagent_infra/groups/brain/spec/deployment/release_process.yaml`

适用路径：
- `groups/brain/projects/infrastructure/brain_ipc`
- `groups/brain/projects/infrastructure/agentctl`
- `groups/brain/projects/infrastructure/brain_gateway`
- 以及其他 `groups/brain/projects/infrastructure/<service>/`

标准入口：

```bash
SERVICE_ROOT=/xkagent_infra/groups/brain/projects/infrastructure/<service>
cd "$SERVICE_ROOT"

# 1. 先看项目声明
cat project.yaml

# 2. 构建 / 测试
make build
make test        # 若 Makefile 提供

# 3. 生成版本
make release VERSION=<x.y.z>

# 4. 部署到 /xkagent_infra/brain/infrastructure/service/<service>/
make deploy VERSION=<x.y.z>

# 5. 若 Makefile 提供 register / restart / verify，继续执行
make register VERSION=<x.y.z>
make verify
```

约束：
- `groups/.../infrastructure/<service>` 是开发源
- `/xkagent_infra/brain/infrastructure/service/<service>/` 是运行态，不能直接手改
- 发布必须把实际文件复制到 `brain/infrastructure/service/`，不能用软链接替代
- 是否需要 `register` / `restart` / `rollback` 以该 service 的 Makefile 为准

---

## 新增 skill 完整流程

> 深入规则：`spec_ref § skill_publish_flow`

```bash
PUBLISH_BASE=/xkagent_infra/brain/base/scripts/publish_base.sh

Step 1  在 groups/brain/projects/base/skill/<name>/SKILL.md 编写 skill
Step 2  在 skill_bindings.yaml 注册到对应 role 或 agent
Step 3  $PUBLISH_BASE --dry-run --domain skill
Step 4  $PUBLISH_BASE --publish --domain skill
Step 5  $PUBLISH_BASE --dry-run --domain agents
Step 6  $PUBLISH_BASE --publish --domain agents
```

约束：
- Step 4 必须在 Step 6 之前
- agents 域读取的是发布态 `brain/base/skill/`
- Step 5 dry-run 会列出每个 agent 的有效 skill 集合和 stale skills，必须人工确认

---

## 刷新 runtime 配置

> 深入规则：`spec_ref § runtime_configs`

runtime 配置（`skill_bindings` / `lep_bindings` / `agents_registry`）直接改文件即生效，不经过 `publish_base.sh`。

但改完后必须让 agent 吃到新配置：

```bash
AGENTCTL="python3 /xkagent_infra/brain/infrastructure/service/agentctl/bin/agentctl \
  --config-dir /xkagent_infra/brain/infrastructure/config/agentctl"

$AGENTCTL apply-config <agent-name> --apply
$AGENTCTL restart <agent-name> --apply
$AGENTCTL online
```

---

## 合并 pending 批次

> 深入规则：`spec_ref § pending_workflow`

pending 批次结构：`/xkagent_infra/runtime/update_brain/pending/<batch>/base/**`

```bash
PENDING=/xkagent_infra/runtime/update_brain/pending
SOURCE=/xkagent_infra/groups/brain/projects/base
PUBLISH_BASE=/xkagent_infra/brain/base/scripts/publish_base.sh

# 1. 查看待处理批次
ls "$PENDING"

# 2. 查看指定批次 CHANGELOG
cat "$PENDING/<batch>/CHANGELOG.md"

# 3. diff 确认变更内容
diff -rq "$SOURCE/<domain>/" "$PENDING/<batch>/base/<domain>/"

# 4. 合并到 source
cp -r "$PENDING/<batch>/base/." "$SOURCE/"

# 5. 发布受影响 domain
$PUBLISH_BASE --dry-run --domain <domain>
$PUBLISH_BASE --publish --domain <domain>

# 6. 归档批次
mv "$PENDING/<batch>" /xkagent_infra/runtime/update_brain/completed/
```

约束：
- 必须有 PMO 审批记录才能执行 Step 4
- Step 4 前必须 diff 确认，不能盲合并
- domain 从 batch 的 `base/` 子目录名推断

---

## 发布后验证

> 深入规则：`spec_ref § validation`

- [ ] 目标文件存在于 `/xkagent_infra/brain/base/<domain>/` 或 `/xkagent_infra/brain/infrastructure/service/<service>/`
- [ ] 受影响 agent 的 `settings.local.json` 已刷新
- [ ] `agentctl online` 显示 agent 在线
- [ ] 抽查 agent `.claude/skills/` 包含预期 skill

---

## 边界说明

本 skill 只覆盖 Type 1 发布：

- pending batch 合并
- `/xkagent_infra/groups/brain/projects/base` → `/xkagent_infra/brain/base` 的 domain 发布
- `/xkagent_infra/groups/brain/projects/infrastructure/<service>` → `/xkagent_infra/brain/infrastructure/service/<service>` 的服务发布入口
- `agents` 域 skill 分发
- runtime config 刷新

本 skill 不覆盖：

- 整体 semver / git tag / release note 发布
- docker image build / push / digest 校验

---

## Spec 引用

| 场景 | 读取路径 | 读取时机 |
|------|----------|----------|
| base domain 说明 / 约束 | `spec_ref § base_publish.domain_notes` | 进入发布 base 域时 |
| skill 发布六步约束 | `spec_ref § skill_publish_flow.constraints` | 新增 skill 时 |
| runtime 配置边界 | `spec_ref § runtime_configs` | 刷新 runtime 时 |
| infrastructure 服务发布规则 | `/xkagent_infra/groups/brain/spec/deployment/release_process.yaml` | 发布 infrastructure service 时 |
| 验证清单 | `spec_ref § validation` | 发布完成后 |

`spec_ref` = `/brain/base/spec/policies/deployment/base_publish.yaml`
