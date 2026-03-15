# agents_registry.yaml 配置文件迁移

**迁移时间**: 2026-02-13 19:10:00
**迁移原因**: 配置文件与代码分离，架构优化

---

## 迁移内容

### 旧路径（已废弃）
```
/brain/groups/org/brain_system/projects/agent_orchestrator/config/agents_registry.yaml
          ↑ 业务层                ↑ 项目                   ↑ 配置混在项目里
```

**问题**:
- 全局配置文件放在特定项目下，耦合度高
- 其他服务引用时路径冗长复杂
- 配置和代码没有分离

### 新路径（当前）
```
/brain/infrastructure/config/agentctl/agents_registry.yaml
          ↑ 基础设施层  ↑ 配置层  ↑ 服务配置
```

**优点**:
- ✅ 职责分离：代码在 service/，配置在 config/
- ✅ 路径简洁：独立的配置目录
- ✅ 独立性：配置不依赖项目实现
- ✅ 一致性：和 `/brain/infrastructure/hooks/` 模式一致

---

## 修改的文件

### 1. 配置文件迁移
```bash
/brain/groups/org/brain_system/projects/agent_orchestrator/config/agents_registry.yaml
    ↓ 复制到
/brain/infrastructure/config/agentctl/agents_registry.yaml
```

### 2. 代码更新

#### `/brain/infrastructure/service/service-agentctl/config/loader.py`
```python
# 旧路径
DEFAULT_CONFIG_DIR = Path(
    os.environ.get(
        "AGENT_MANAGER_CONFIG_DIR",
        "/brain/groups/org/brain_system/projects/agent_orchestrator/config",
    )
)

# 新路径
DEFAULT_CONFIG_DIR = Path(
    os.environ.get(
        "AGENT_MANAGER_CONFIG_DIR",
        "/brain/infrastructure/config/agentctl",
    )
)
```

#### `/brain/infrastructure/service/service-agentctl/services/provisioner.py`
```python
# 更新生成的 CLAUDE.md 注释
"- Managed by `service-agentctl` via `/brain/infrastructure/config/agentctl/agents_registry.yaml`."
```

---

## 验证结果

### ✅ 配置加载成功
```bash
Config dir: /brain/infrastructure/config/agentctl
Registry version: 2.0
Groups: ['brain_system', 'xkquant']
Total agents: 16
```

### ✅ Hooks 配置正确加载
```bash
agent-system_pmo: ['pre_tool_use', 'post_tool_use', 'session_start', 'session_end']
agent-system_frontdesk: ['pre_tool_use', 'post_tool_use', 'session_start']
agent-xkquant_researcher: ['session_start']
```

---

## 架构对比

### 迁移前
```
/brain/
├── groups/
│   └── org/brain_system/
│       └── projects/
│           └── agent_orchestrator/      # 项目代码
│               ├── src/
│               └── config/              # ❌ 配置混在项目里
│                   └── agents_registry.yaml
│
└── infrastructure/
    └── service/
        └── agent-ctl/                   # agentctl 代码
            ├── bin/agentctl
            └── services/
```

### 迁移后
```
/brain/
├── groups/
│   └── org/brain_system/
│       └── projects/
│           └── agent_orchestrator/      # 项目代码（纯代码）
│               └── src/
│
└── infrastructure/
    ├── config/                          # ✅ 全局配置层
    │   └── agentctl/
    │       └── agents_registry.yaml     # 全局 agent 配置
    │
    └── service/
        └── agent-ctl/                   # agentctl 服务（纯代码）
            ├── bin/agentctl
            ├── services/
            └── config/                  # 代码级配置（默认值、schema）
```

---

## 环境变量

如果需要使用自定义配置路径，设置环境变量：
```bash
export AGENT_MANAGER_CONFIG_DIR=/path/to/custom/config
```

默认值：`/brain/infrastructure/config/agentctl`

---

## 后续待优化

### Audit 日志路径
**当前**: `/brain/groups/brain_system_group/projects/agentctl/memory/audit/`
**建议**: `/xkagent_infra/runtime/logs/agentctl/audit/`

**原因**: audit 日志是运行时数据，应该和其他运行时日志放在一起

**迁移计划**: 后续单独创建 SPEC 处理

---

## 向后兼容

### 环境变量兜底
如果有外部系统仍然使用旧路径，可以通过环境变量指定：
```bash
export AGENT_MANAGER_CONFIG_DIR=/brain/groups/org/brain_system/projects/agent_orchestrator/config
```

### 旧文件处理
**建议**: 保留旧文件 30 天，添加 README 指向新位置

```bash
# 在旧位置创建 README
cat > /brain/groups/org/brain_system/projects/agent_orchestrator/config/README.md <<EOF
# ⚠️ 此目录已废弃

**agents_registry.yaml 已迁移到**:
\`/brain/infrastructure/config/agentctl/agents_registry.yaml\`

**原因**: 配置文件与代码分离

**迁移时间**: 2026-02-13

**文档**: /brain/infrastructure/config/agentctl/MIGRATION.md
EOF
```

---

## 相关文档

- Base Spec: `/brain/base/spec/policies/agents/agents_registry_spec.yaml`
- Hooks 规范: `/brain/infrastructure/hooks/releases/HOOKS-SPEC-ADDED.md`
- Registry 配置: `/brain/infrastructure/hooks/releases/REGISTRY-HOOKS-ADDED.md`
