# Hooks 系统部署指南

> 最后更新: 2026-02-15 | 版本: v2.2.0

## 架构概览

```
hooks/
├── src/                          ← 开发源码 (修改后不影响运行中的 agent)
│   ├── handlers/tool_validation/v1/python/
│   │   └── handler.py            ← 主 handler (Phase 0 角色检查 + 12 gate)
│   ├── lep/
│   │   ├── role_scope.py         ← 角色作用域引擎
│   │   ├── lep_check.c           ← C 二进制快速检查 (编译产物: lep_check)
│   │   └── lep.py                ← LEP 配置加载器
│   ├── checkers/                 ← path_checker, audit_logger, file_org_checker
│   └── utils/python/             ← io_helper 等工具
│
├── rules/                        ← 角色规则 (配置，共享给所有 release)
│   └── roles/{role}/gates.yaml   ← pmo/architect/dev/devops/qa/frontdesk
│
├── releases/                     ← 代码快照 (独立副本，互不影响)
│   └── v2.2.0/
│       ├── bin/v2/               ← 入口脚本
│       ├── src/                  ← 源码快照
│       ├── rules -> ../../rules  ← 共享规则 symlink
│       └── VERSION               ← 版本元信息 + hash
│
├── bin/
│   └── current -> ../releases/v2.2.0/bin/v2   ← 全局默认版本
│
└── scripts/
    └── snapshot_release.sh       ← 发布脚本
```

### 调用链

```
Claude Code (agent 运行时)
  │
  ├── 读 settings.local.json → hooks.PreToolUse[0].hooks[0]
  │     command: hooks/bin/current/pre_tool_use
  │     env: { BRAIN_AGENT_ROLE, BRAIN_AGENT_GROUP, BRAIN_SCOPE_PATH, ... }
  │
  └── fork 子进程:
        env vars 注入 → pre_tool_use (入口) → handler.py
          ├── Phase 0: role_scope.py 读 env vars → 加载 rules/roles/{role}/gates.yaml
          ├── Phase 1-14: LEP gates (lep.yaml + lep_check binary)
          └── 输出: { block: true/false, blockMessage: "..." }
```

### 角色区分机制

所有 agent 共用同一个 hook 脚本，通过 **环境变量** 区分角色：

| 环境变量 | 来源 | 作用 |
|----------|------|------|
| `BRAIN_AGENT_NAME` | agents_registry.yaml | Agent 标识 |
| `BRAIN_AGENT_ROLE` | agents_registry.yaml → config_generator | 加载对应 gates.yaml |
| `BRAIN_AGENT_GROUP` | agents_registry.yaml → config_generator | 展开 `{group}` 占位符 |
| `BRAIN_SCOPE_PATH` | config_generator 推算 | 作用域基路径 |

这些 env vars 由 agentctl 的 `config_generator.py` 在生成 `settings.local.json` 时写入。

---

## 发布流程

### 创建 Release

```bash
cd /brain/infrastructure/service/agent_abilities/hooks

# 创建新 release 并激活
bash scripts/snapshot_release.sh v2.3.0 --activate

# 仅创建，不激活 (用于灰度发布)
bash scripts/snapshot_release.sh v2.3.0
```

Release 脚本执行:
1. 预检查: src/, bin/, lep_check binary 完整性
2. `cp -rL` 快照 src/ (解析所有 symlinks，创建独立副本)
3. 复制 bin/v2/ 入口脚本
4. Symlink rules/ 到共享规则目录
5. 写入 VERSION 文件 (版本号、commit hash、文件 hash)
6. 验证: import 测试、文件完整性检查
7. 可选: 更新 bin/current symlink

### 回滚

```bash
bash scripts/snapshot_release.sh --rollback v2.2.0
```

### 版本锁定 (Per-Agent)

在 `agents_registry.yaml` 中设置 `hooks_version`:

```yaml
# 锁定到特定版本 (不跟随 bin/current)
agent_xkquant_architect:
  hooks_version: v2.2.0

# 跟随 bin/current (默认行为，不需要设置)
agent_system_dev1:
  # hooks_version 不设置
```

`config_generator.py` 的选择逻辑:
- 设置了 `hooks_version: v2.2.0` → `releases/v2.2.0/bin/v2/pre_tool_use`
- 未设置 → `bin/current/pre_tool_use` (跟随 symlink)

锁定后需重启 agent 生效:
```bash
agentctl restart agent_xkquant_architect
```

---

## 角色作用域规则

### 规则文件位置

```
hooks/rules/roles/
├── pmo/gates.yaml         # PMO: workflow/memory/tasks, 不可写代码
├── architect/gates.yaml   # 架构师: spec templates/组内 spec/knowledge
├── dev/gates.yaml         # 开发: projects/agent workdir/memory
├── devops/gates.yaml      # 运维: infrastructure/runtime/deploy
├── qa/gates.yaml          # 测试: tests/qa/test_reports
└── frontdesk/gates.yaml   # 前台: 仅 agent workdir/memory
```

### 规则语法

```yaml
scope:
  allowed_write:          # 白名单 (支持 ** glob, {group} 占位符)
    - /brain/groups/org/{group}/**/projects/**
    - /brain/groups/org/{group}/agents/agent_{group}_dev*/**
  denied_write:           # 黑名单 (优先于白名单)
    - /brain/base/spec/**
    - /brain/infrastructure/**

gate_overrides:           # 角色特定 gate 优先级覆盖
  G-GATE-NAWP:
    priority: CRITICAL
```

### 检查优先级

1. `denied_write` 匹配 → **BLOCK**
2. `allowed_write` 有定义且匹配 → ALLOW
3. `allowed_write` 有定义但不匹配 → **BLOCK**
4. 无 `allowed_write` 规则 → ALLOW (宽松默认)

### 角色权限矩阵

| 路径 | dev | architect | devops | pmo | qa | frontdesk |
|------|-----|-----------|--------|-----|-----|-----------|
| base/spec/core/ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| base/spec/templates/ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| base/workflow/ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| {group}/spec/ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| {group}/projects/src/ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| infrastructure/ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| runtime/ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| memory/ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 跨组写入 | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

---

## 日常操作

### 修改规则 (不需要新 release)

角色规则 `rules/roles/*/gates.yaml` 是共享的，修改即时生效（下次工具调用）:

```bash
vim hooks/rules/roles/dev/gates.yaml
# 保存后立即对所有 dev 角色 agent 生效
```

### 修改 handler 代码 (需要新 release)

```bash
# 1. 修改源码
vim hooks/src/handlers/tool_validation/v1/python/handler.py

# 2. 编译 C 二进制 (如果修改了 lep_check.c)
gcc -O2 -o hooks/src/lep/lep_check hooks/src/lep/lep_check.c

# 3. 测试
echo '{"toolName":"Write","toolInput":{"file_path":"/brain/base/spec/core/lep.yaml","content":"test"}}' | \
  BRAIN_AGENT_ROLE=dev BRAIN_AGENT_GROUP=brain_system BRAIN_SCOPE_PATH=/brain/groups/org/brain_system \
  python3 hooks/bin/v2/pre_tool_use

# 4. 创建 release
bash hooks/scripts/snapshot_release.sh v2.3.0 --activate

# 5. 验证 release 工作正常
echo '{"toolName":"Write","toolInput":{"file_path":"/brain/base/spec/core/lep.yaml","content":"test"}}' | \
  BRAIN_AGENT_ROLE=dev BRAIN_AGENT_GROUP=brain_system BRAIN_SCOPE_PATH=/brain/groups/org/brain_system \
  python3 hooks/bin/current/pre_tool_use
# 期望: block=true
```

### 灰度发布

```bash
# 1. 创建 release (不激活)
bash scripts/snapshot_release.sh v2.3.0

# 2. 先锁定一个 agent 到新版本
# 在 agents_registry.yaml 中:
#   agent_system_dev1:
#     hooks_version: v2.3.0

# 3. 重启该 agent
agentctl restart agent_system_dev1

# 4. 观察 24h 无问题后，全量激活
bash scripts/snapshot_release.sh --rollback v2.3.0  # 这里是 activate 不是 rollback
# 或直接:
ln -sfn ../releases/v2.3.0/bin/v2 hooks/bin/current

# 5. 移除版本锁定
# 删除 agents_registry.yaml 中的 hooks_version
```

---

## 版本隔离原理

```
修改 src/handler.py 引入 bug
  ↓
bin/current → releases/v2.2.0/bin/v2/ → releases/v2.2.0/src/handler.py
                                          ↑ 这是 v2.2.0 创建时的快照副本
                                          ↑ 与 src/handler.py 完全独立
  ↓
运行中的 agent 不受影响 ✓
```

**关键**: `cp -rL` 创建的是完整副本（解析 symlinks），不是引用。只有创建新 release 时才会包含新代码。

### 什么需要 release，什么不需要

| 修改内容 | 需要新 release? | 需要重启 agent? |
|----------|----------------|----------------|
| `rules/roles/*/gates.yaml` | ❌ 不需要 | ❌ 不需要 |
| `src/handlers/handler.py` | ✅ 需要 | ❌ 不需要 |
| `src/lep/role_scope.py` | ✅ 需要 | ❌ 不需要 |
| `src/lep/lep_check.c` | ✅ 需要 (含编译) | ❌ 不需要 |
| `config_generator.py` (env vars) | ❌ 不需要 | ✅ 需要 |
| `agents_registry.yaml` (role) | ❌ 不需要 | ✅ 需要 |

---

## 故障排查

### Hook 没有拦截

```bash
# 1. 确认 bin/current 指向正确的 release
ls -la hooks/bin/current
# 应该指向 ../releases/v2.x.x/bin/v2

# 2. 确认 release 中 handler 存在
ls hooks/releases/v2.2.0/src/handlers/tool_validation/v1/python/handler.py

# 3. 手动测试 hook
echo '{"toolName":"Write","toolInput":{"file_path":"/brain/base/spec/core/lep.yaml"}}' | \
  BRAIN_AGENT_ROLE=dev BRAIN_AGENT_GROUP=brain_system \
  BRAIN_SCOPE_PATH=/brain/groups/org/brain_system \
  python3 hooks/bin/current/pre_tool_use

# 4. 检查 agent 的 settings.local.json
jq '.hooks.PreToolUse[0].hooks[0].env' \
  /brain/groups/org/brain_system/agents/agent_system_dev1/.claude/settings.local.json
```

### 角色检查未生效

```bash
# 确认 env vars 在 settings.local.json 中
jq '.hooks.PreToolUse[0].hooks[0].env.BRAIN_AGENT_ROLE' \
  /path/to/agent/.claude/settings.local.json

# 如果是 null 或 "default"，需要:
# 1. 在 agents_registry.yaml 中添加 role 字段
# 2. agentctl restart <agent_name>
```

### Release 损坏

```bash
# 回滚到上一个 release
bash scripts/snapshot_release.sh --rollback v2.1.0

# 或重新创建当前版本
rm -rf hooks/releases/v2.2.0
bash scripts/snapshot_release.sh v2.2.0 --activate
```

---

## 相关文档

- 角色规则: `hooks/rules/roles/*/gates.yaml`
- LEP Gates 定义: `/brain/base/spec/core/lep.yaml`
- Config 生成器: `/brain/infrastructure/service/agent-ctl/services/config_generator.py`
- Agent 注册表: `/brain/infrastructure/config/agentctl/agents_registry.yaml`

---

**维护者**: Brain System Team
**当前版本**: v2.2.0
