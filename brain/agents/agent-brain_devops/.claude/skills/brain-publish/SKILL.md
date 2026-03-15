---
name: brain-publish
description: 执行 Brain Base 的发布与运行时刷新；当任务涉及发布 `/xkagent_infra/groups/brain/projects/base` 到 `/xkagent_infra/brain/base`、执行 `publish_base.sh`、刷新 `skill_bindings/lep_bindings`、或要求 manager/devops 完成 base 发布和 agent 生效验证时使用。
metadata:
  status: active
  source_project: /xkagent_infra/groups/brain/projects/base
  publish_target: /xkagent_infra/brain/base/skill/brain-publish
---

# Brain Publish

这个 skill 用于执行 Brain Base 的标准发布流程。

优先读取：
- `/brain/base/spec/policies/deployment/base_publish.yaml`
- `/brain/base/knowledge/guides/publish/base_publish.md`

## 什么时候用

- 发布 `projects/base` 的 `skill/hooks/spec/knowledge/workflow`
- 需要判断某个改动是 `base` 发布还是 runtime 配置刷新
- 发布后要让 agent 真正吃到新配置

## 核心规则

1. 先判断变更类型
   - `projects/base/*` 变更 → 走 `publish_base.sh`
   - `brain/infrastructure/config/agentctl/*` 变更 → 不走 `publish_base.sh`

2. 先 dry-run 再 publish

3. 影响 agent 运行态时，发布后必须继续：
   - `agentctl apply-config --apply`
   - `agentctl restart --apply`

4. 不直接手改 `/xkagent_infra/brain/base`

## 最小执行流程

1. 确认发布域
2. 执行 `publish_base.sh --dry-run --domain <domain>`
3. 执行 `publish_base.sh --publish --domain <domain>`
4. 如涉及运行态，执行：
   - `agentctl apply-config`
   - `agentctl restart`
5. 验证：
   - `agentctl online`
   - 目标文件存在
   - `settings.local.json`
   - `agent_runtime.json`

## 常用命令

```bash
/xkagent_infra/groups/brain/projects/base/scripts/publish_base.sh --dry-run --domain skill
/xkagent_infra/groups/brain/projects/base/scripts/publish_base.sh --publish --domain skill

python3 /xkagent_infra/brain/infrastructure/service/agentctl/bin/agentctl \
  --config-dir /xkagent_infra/brain/infrastructure/config/agentctl \
  apply-config agent-brain_manager agent-system_devops --apply

python3 /xkagent_infra/brain/infrastructure/service/agentctl/bin/agentctl \
  --config-dir /xkagent_infra/brain/infrastructure/config/agentctl \
  restart agent-brain_manager agent-system_devops --apply
```

## 角色建议

- `manager`：判断发布范围、审批、收口
- `devops`：执行发布、刷新运行态、验证与回滚
