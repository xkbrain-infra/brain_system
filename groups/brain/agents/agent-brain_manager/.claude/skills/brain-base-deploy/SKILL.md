---
id: G-SKILL-BRAIN-BASE-DEPLOY
name: brain-base-deploy
description: "Use this skill when asked to deploy, publish, diff, merge, rollback, or check versions of /brain/base/ domains (spec, workflow, knowledge, evolution, skill, hooks, mcp_server, index)."
user-invocable: true
disable-model-invocation: false
allowed-tools: mcp__brain_base_deploy__deploy_diff, mcp__brain_base_deploy__deploy_publish, mcp__brain_base_deploy__deploy_merge, mcp__brain_base_deploy__deploy_versions, mcp__brain_base_deploy__deploy_rollback, mcp__brain_base_deploy__deploy_stats
argument-hint: "[diff|publish|merge|versions|rollback|stats] [target]"
---

# brain-base-deploy — /brain/base/ 构建与部署

专属 `agent-brain-manager` 的部署技能。通过 `brain_base_deploy` MCP server 操作 `/brain/base/` 域的构建与发布。

## MCP Tools

| Tool | 说明 |
|------|------|
| `deploy_diff` | 查看 base ↔ src 差异，确认什么需要更新 |
| `deploy_publish` | **主命令**：全流程 diff→merge→build→deploy |
| `deploy_merge` | 仅将 /brain/base/ 变更同步回 src/（base→src） |
| `deploy_versions` | 列出所有历史发布版本 |
| `deploy_rollback` | 回滚 /brain/base/ 到指定版本 |
| `deploy_stats` | 生成 spec/LEP/hooks 覆盖率统计 |

## 可用 Targets

| Target | 描述 |
|--------|------|
| `spec` | Spec 规范文档（含 LEP gates） |
| `workflow` | 工作流程文档 |
| `knowledge` | 知识库 |
| `evolution` | 演进引擎 |
| `skill` | 系统能力说明 |
| `hooks` | Agent Hooks 运行时 |
| `mcp_server` | brain_ipc_c MCP server（C 编译） |
| `index` | base/ 域统一入口 |
| `docs` | spec+workflow+knowledge+evolution+skill+index 合集 |
| `all` | 全部（含 hooks + mcp_server） |

## 标准工作流

### 场景 1：有人直接改了 /brain/base/，需要同步并发布
```
1. deploy_diff(target)          # 确认差异
2. deploy_merge(target)         # base → src 同步
3. deploy_publish(target)       # 全流程发布
```

### 场景 2：src/ 已更新，直接发布
```
1. deploy_diff(target)          # 确认 src 有变更
2. deploy_publish(target)       # 自动 merge + build + deploy
```

### 场景 3：发布出问题，需要回滚
```
1. deploy_versions()            # 查看可用版本
2. deploy_rollback(version)     # 回滚到指定版本
```

## 参数解析

`/brain-base-deploy $ARGUMENTS`:
- `diff [target]` → `deploy_diff`
- `publish <target>` → `deploy_publish`
- `merge <target>` → `deploy_merge`
- `versions` → `deploy_versions`
- `rollback <version>` → `deploy_rollback`
- `stats` → `deploy_stats`
- 无参数 → `deploy_diff(docs)` 查看全局差异

## 注意事项

- `deploy_publish` 默认 `auto_merge=true`，会自动确认 merge 步骤
- `hooks` target 构建较慢（含 Python 语法检查 + 集成测试）
- `mcp_server` target 需要 C 编译环境（gcc/make）
- rollback 会覆盖 /brain/base/，操作前确认版本号正确
