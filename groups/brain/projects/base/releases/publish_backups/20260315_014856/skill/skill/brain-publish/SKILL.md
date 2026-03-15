---
id: G-SKILL-DEPLOY-BRAIN-PUBLISH
name: brain-publish
description: "当任务涉及发布 projects/base 变更、新增或修改 skill、将 skill 部署到 agent、或刷新 agent 运行态配置时使用。"
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Edit, Bash, Glob
argument-hint: "[skill|spec|hooks|knowledge|workflow|agents|runtime|all]"
metadata:
  status: active
  source_project: /xkagent_infra/groups/brain/projects/base
  publish_target: /xkagent_infra/brain/base/skill/brain-publish
  spec_ref: /brain/base/spec/policies/deployment/base_publish.yaml
---

# brain-publish

<!-- L1 -->
## 触发场景

| 情境 | 跳转 |
|------|------|
| 修改了 skill / spec / hooks / knowledge / workflow | → [发布 base 域](#发布-base-域) |
| 新增了一个 skill | → [新增 skill 完整流程](#新增-skill-完整流程) |
| 修改了 skill_bindings / lep_bindings / agents_registry | → [刷新 runtime 配置](#刷新-runtime-配置) |
| 不确定改动属于哪类 | → [判断变更类型](#判断变更类型) |

不适用：
- 直接修改 `/xkagent_infra/brain/base/` — 禁止，brain/base 是发布态不是开发源

---

<!-- L2 -->
## 判断变更类型

问自己：

1. **改动在哪里？**
   - `groups/brain/projects/base/*` → 走 publish_base.sh
   - `brain/infrastructure/config/agentctl/*.yaml` → 走 agentctl，不走 publish_base.sh

2. **改动是什么？**
   - skill / spec / hooks / knowledge / workflow → [发布 base 域](#发布-base-域)
   - skill_bindings / lep_bindings / agents_registry → [刷新 runtime 配置](#刷新-runtime-配置)

3. **是否同时新增了 skill？**
   - 是 → [新增 skill 完整流程](#新增-skill-完整流程)

---

<!-- L3 -->
## 发布 base 域

> 深入规则：`spec_ref § base_publish.domain_notes`

```bash
# 1. dry-run 确认
/xkagent_infra/groups/brain/projects/base/scripts/publish_base.sh \
  --dry-run --domain <domain>

# 2. 正式发布
/xkagent_infra/groups/brain/projects/base/scripts/publish_base.sh \
  --publish --domain <domain>
```

`<domain>` 可选值：`skill` `spec` `hooks` `knowledge` `workflow` `mcp` `evolution` `agents` `all`

**约束：**
- 必须先 dry-run，确认输出无误再 publish
- `--domain all` 包含 agents 域，会同时分发 skill 到所有 agent

---

## 新增 skill 完整流程

> 深入规则：`spec_ref § skill_publish_flow`

```
Step 1  在 groups/brain/projects/base/skill/<name>/SKILL.md 编写 skill
Step 2  在 skill_bindings.yaml 注册到对应 role 或 agent
Step 3  publish_base.sh --dry-run --domain skill
Step 4  publish_base.sh --publish --domain skill
Step 5  publish_base.sh --dry-run --domain agents   ← 确认 stale skill 清单
Step 6  publish_base.sh --publish --domain agents
```

**约束：**
- Step 4 必须在 Step 6 之前，agents 域读取的是发布态 brain/base/skill/
- Step 5 dry-run 会列出每个 agent 的有效 skill 集合和将被删除的 stale skills，必须人工确认

---

## 刷新 runtime 配置

> 深入规则：`spec_ref § runtime_configs`

runtime 配置（skill_bindings / lep_bindings / agents_registry）直接改文件即生效，不经过 publish_base.sh。

但改完后必须让 agent 吃到新配置：

```bash
AGENTCTL="python3 /xkagent_infra/brain/infrastructure/service/agentctl/bin/agentctl \
  --config-dir /xkagent_infra/brain/infrastructure/config/agentctl"

# 生成新配置（dry-run 默认，加 --apply 才真正写入）
$AGENTCTL apply-config <agent-name> --apply

# 重启 agent
$AGENTCTL restart <agent-name> --apply

# 验证上线
$AGENTCTL online
```

---

## 发布后验证

> 深入规则：`spec_ref § validation`

- [ ] 目标文件存在于 `/xkagent_infra/brain/base/<domain>/`
- [ ] 受影响 agent 的 `settings.local.json` 已刷新
- [ ] `agentctl online` 显示 agent 在线
- [ ] 抽查 agent `.claude/skills/` 包含预期 skill

---

## Spec 引用

| 场景 | 读取路径 | 读取时机 |
|------|----------|----------|
| domain 说明 / 约束 | `spec_ref § base_publish.domain_notes` | 进入发布 base 域时 |
| skill 发布六步约束 | `spec_ref § skill_publish_flow.constraints` | 新增 skill 时 |
| runtime 配置边界 | `spec_ref § runtime_configs` | 刷新 runtime 时 |
| 验证清单 | `spec_ref § validation` | 发布完成后 |

`spec_ref` = `/brain/base/spec/policies/deployment/base_publish.yaml`
