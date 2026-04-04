---
id: G-SKILL-DEPLOY-BRAIN-RELEASE
name: brain-release
description: "当任务涉及 Brain 整体版本号、git tag、release notes、版本冻结、或要求定义一次正式 release 时使用。它不负责具体 docker image 构建。"
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Edit, Bash, Glob
argument-hint: "[prepare|tag|notes|verify]"
metadata:
  status: active
  source_project: /xkagent_infra/groups/brain/projects/base
  publish_target: /xkagent_infra/brain/base/skill/brain-release
---

# brain-release

## 触发场景

| 情境 | 处理 |
|------|------|
| 准备 `brain 1.0.0` / `1.1.0` 这类整体版本 | → 使用本 skill |
| 需要 git tag / release notes / changelog 聚合 | → 使用本 skill |
| 需要同步整体版本号与 image 版本号 | → 使用本 skill 决策版本，再交给 `/brain-image-publish` |
| 只是 skill/spec/hooks/workflow 改动进入运行态 | → 使用 `/brain-publish` |
| 只是构建 docker image / push registry | → 使用 `/brain-image-publish` |

## 责任边界

本 skill 负责：

- 定义本次 Brain 正式版本号
- 汇总 release scope 与 release notes
- 决定是否创建 git tag
- 决定 docker image 应使用的版本号

本 skill 不负责：

- `pending -> merge -> publish_base.sh` 这类 Type 1 发布
- 实际执行 docker build / push

## 推荐流程

```bash
RELEASE_VERSION=<semver>

# 1. 冻结 release scope
# - 列出纳入本次 release 的 pending / merged changes
# - 确认 blocker 清零

# 2. 汇总 release notes
# - 记录包含的 domain / service / workflow / skill / platform 变化

# 3. 校验版本同步点
# - Brain 整体版本
# - brain-docker / image 版本

# 4. 创建 tag（示例）
git tag -a "brain-v${RELEASE_VERSION}" -m "brain ${RELEASE_VERSION}"
```

## 版本规则

- PATCH: 内部修复、兼容性不变
- MINOR: 新增功能、向后兼容
- MAJOR: 破坏兼容性或运行模型变化

## 交付物

- release version
- release notes
- git tag plan 或实际 tag
- 下游 image version plan

## 当前缺口

当前 source 内未发现独立的 `brain-release` spec。

在正式落地前，至少需要补清：

- 版本号权威来源文件
- git tag 命名规范
- release notes 模板
- 与 `/brain-image-publish` 的联动规则
