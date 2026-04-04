---
id: G-SKILL-DEPLOY-BRAIN-PUBLISH-IMAGE
name: brain-publish-image
description: "当任务涉及 Brain Docker artifact 构建、镜像 tag、push、digest 校验、或 Published docker 包发布时使用。它不负责定义整体 Brain release 版本。"
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Edit, Bash, Glob
argument-hint: "[build|push|verify|promote]"
metadata:
  status: active
  source_project: /xkagent_infra/groups/brain/projects/base
  publish_target: /xkagent_infra/brain/base/skill/brain-publish-image
---

# brain-publish-image

## 触发场景

| 情境 | 处理 |
|------|------|
| 构建 `brain/docker-base` 镜像 | → 使用本 skill |
| 推送 image tag / 校验 digest | → 使用本 skill |
| 同步 docker Published 域 | → 使用本 skill |
| 需要先决定正式版本号 | → 先使用 `/brain-publish-release` |
| 只是 Brain 内部发布链改动 | → 使用 `/brain-publish` |

## 三域路径

```text
Source   : /xkagent_infra/groups/brain/platform/docker/
Runtime  : /xkagent_infra/app/brain/docker/
Published: /xkagent_infra/brain/platform/docker/
```

## 责任边界

本 skill 负责：

- docker image build
- image tag / push / digest 校验
- docker Published 域校验

本 skill 不负责：

- `pending -> merge -> publish_base.sh` 的 Brain 内部改动发布
- Brain 整体 semver / git tag / release note 决策

## 当前入口现状

当前 source 有一处不一致，执行前必须先确认：

- `index.yaml` 声明的脚本入口是 `scripts/build.sh` / `scripts/start.sh` / `scripts/stop.sh`
- 但当前 `groups/brain/platform/docker/scripts/` 里实际可见的是 `startup.sh` / `migration_preflight.sh` 等文件
- 当前唯一明确存在的 build 脚本是 `services/brain-spec/build.sh`

结论：

- 在入口未统一前，不要把 `scripts/build.sh` 当成既定事实
- 执行 image publish 前，先确认本次使用的真实 build entrypoint

## 推荐流程

```bash
DOCKER_SRC=/xkagent_infra/groups/brain/platform/docker
DOCKER_PUB=/xkagent_infra/brain/platform/docker
IMAGE_TAG=<version>

# 1. 确认本次 build 入口
# - 检查 index.yaml
# - 检查 scripts/ 与 services/*/build.sh

# 2. 构建 image
# - 执行已确认的 build entrypoint

# 3. 校验 tag / digest
# - docker images
# - docker inspect

# 4. 校验 Published 域
# - Dockerfile / compose.yaml / configs / scripts 已同步到 $DOCKER_PUB
```

## 读取参考

- `/xkagent_infra/groups/brain/platform/docker/index.yaml`
- `/xkagent_infra/groups/brain/platform/docker/README.md`
- `/xkagent_infra/brain/platform/docker/manifests/index.yaml`

## 当前缺口

在 source 中，image publish 还缺少一份统一 spec 来定义：

- build entrypoint
- tag 策略
- push registry 流程
- Published 域同步责任
- 与 `/brain-publish-release` 的版本联动关系
