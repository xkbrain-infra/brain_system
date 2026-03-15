# Infrastructure Service 目录结构指南

## 规范来源

`/brain/base/spec/standards/infra/service_structure.yaml` (STD-SVC-STRUCT-001)

## 核心原则

**`releases/{version}/bin/` 是服务的外部接口。** 所有外部引用通过 `bin/current` 软链接或 `releases/{version}/bin/` 访问。

## 标准结构

```
service_name/
├── releases/                    # 版本化发布（必须）
│   ├── v1.0.0/
│   │   └── bin/                # 该版本的外部入口
│   │       └── entry_point
│   └── v1.1.0/
│       └── bin/
│           └── entry_point
├── bin/
│   └── current -> ../releases/v1.1.0/bin   # 当前版本软链接
├── src/                         # 源码（外部不引用）
└── config/                      # 配置（可选）
```

## 已有成功案例：agent_abilities/hooks

```
hooks/
├── releases/
│   ├── v2.0.0/
│   │   ├── bin/
│   │   │   ├── pre_tool_use
│   │   │   └── post_tool_use
│   │   └── configs/
│   └── v2.1.0/
│       └── bin/
│           ├── pre_tool_use
│           └── post_tool_use
├── bin/
│   ├── current -> ../releases/v2.1.1/bin    # 外部引用此路径
│   ├── v1/
│   └── v2/
├── src/
├── build/
└── tests/
```

外部引用: `/brain/infrastructure/service/agent_abilities/hooks/bin/current/pre_tool_use`

## 外部引用规则

### 推荐：通过 bin/current（自动跟随版本）

```json
// settings.local.json
{
  "command": "/brain/infrastructure/service/agent_abilities/hooks/bin/current/pre_tool_use"
}
```

```python
# Python importlib
_spec = importlib.util.spec_from_file_location(
    "daemon_client",
    "/brain/infrastructure/service/utils/ipc/bin/current/daemon_client.py"
)
```

### 可选：锁定特定版本

```
/brain/infrastructure/service/agent_abilities/hooks/releases/v2.1.0/bin/pre_tool_use
```

### 禁止：直接引用源码或根目录文件

```python
# ❌ 错误
"/brain/infrastructure/service/utils/ipc/daemon_client.py"
"/brain/infrastructure/service/utils/ipc/src/daemon_client.py"
"/brain/infrastructure/service/gateway/webhook_gateway.py"
```

## 版本管理

### 发布新版本

```bash
# 1. 创建版本目录
mkdir -p /brain/infrastructure/service/{name}/releases/v1.2.0/bin/

# 2. 构建/复制入口文件到新版本 bin/
cp src/entry_point releases/v1.2.0/bin/

# 3. 更新 current 软链接
cd /brain/infrastructure/service/{name}/bin/
rm current && ln -s ../releases/v1.2.0/bin current
```

### 回滚

```bash
# 将 current 指回旧版本，所有外部引用自动回滚
cd /brain/infrastructure/service/{name}/bin/
rm current && ln -s ../releases/v1.1.0/bin current
```

## 现有服务合规速查

| 服务 | releases/ | bin/current | 状态 |
|------|-----------|-------------|------|
| agent_abilities/hooks | v2.0.0, v2.1.0 | ✅ | 合规 |
| agent-ctl | - | 有 bin/ 无 releases | 部分合规 |
| dashboard | - | 有 bin/ 无 releases | 部分合规 |
| utils/tmux | - | 有 bin/ 无 releases | 部分合规 |
| agent_abilities/mcp | - | 有 bin/ 无 releases | 部分合规 |
| **utils/ipc** | - | - | **需迁移** |
| **daemon** | - | - | **需迁移** |
| **gateway** | - | - | **需迁移** |
| **timer** | - | - | **需迁移** |
| **monitor** | - | - | **需迁移** |
| **litellm-proxy** | - | - | **需迁移** |
