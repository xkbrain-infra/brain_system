# Brain Infrastructure 服务迁移计划

## 目标

将所有 `/xkagent_infra/brain/infrastructure/service/` 下的**源码**迁移到 `/xkagent_infra/groups/brain/projects/infrastructure/`

## 现状分析

### 需要迁移的服务（有 src/ 目录）

| 服务名 | 当前路径 | 目标路径 | 优先级 |
|--------|----------|----------|--------|
| agent_abilities | /brain/infrastructure/service/agent_abilities/ | /groups/brain/projects/infrastructure/agent_abilities/ | 高 |
| brain_agent_proxy | /brain/infrastructure/service/brain_agent_proxy/ | /groups/brain/projects/infrastructure/brain_agent_proxy/ | 高 |
| brain_gateway | /brain/infrastructure/service/brain_gateway/ | /groups/brain/projects/infrastructure/brain_gateway/ | 高 |
| brain_google_api | /brain/infrastructure/service/brain_google_api/ | /groups/brain/projects/infrastructure/brain_google_api/ | 中 |
| brain_ipc | /brain/infrastructure/service/brain_ipc/ | /groups/brain/projects/infrastructure/brain_ipc/ | 高 |
| brain_ipc_pty | /brain/infrastructure/service/brain_ipc_pty/ | /groups/brain/projects/infrastructure/brain_ipc_pty/ | 高 |
| brain_task_manager | /brain/infrastructure/service/brain_task_manager/ | /groups/brain/projects/infrastructure/brain_task_manager/ | 高 |
| brain_telegram_api | /brain/infrastructure/service/brain_telegram_api/ | /groups/brain/projects/infrastructure/brain_telegram_api/ | 中 |

### 已经是运行时的服务（无需迁移）

| 服务名 | 状态 |
|--------|------|
| agent_vectordb | ✅ 已经是运行时 |
| agentctl | ✅ 已经是运行时 |
| brain_dashboard | ✅ 已迁移完成 |
| brain_monitor | ✅ 已经是运行时 |
| brain_supervisor_bridge | ✅ 已经是运行时 |
| brain_timer | ✅ 已经是运行时 |

### 其他服务

| 服务名 | 类型 |
|--------|------|
| brain_auth_manager | 配置服务 |
| brain_health_check | 脚本服务 |
| utils | 工具脚本 |

## 迁移流程

对每个服务执行：

### 1. 创建项目结构

```
/groups/brain/projects/infrastructure/{service}/
├── Makefile              # 从 brain_dashboard 复制模板
├── project.yaml
├── build/
│   └── README.md
├── src/                  # 从 infrastructure/service/ 迁移
├── tests/                # 如有
└── releases/             # 版本目录
```

### 2. Makefile 关键配置

```makefile
PROJECT_NAME := {service}
PROJECT_ROOT := /xkagent_infra/groups/brain/projects/infrastructure/$(PROJECT_NAME)
INFRA_SERVICE := /xkagent_infra/brain/infrastructure/service/$(PROJECT_NAME)

# 检查代码版本（某些服务需要）
check-code-version:
    # 检查 src/app.py 或相关文件
```

### 3. 迁移步骤

```bash
# 1. 在 groups 创建项目
cd /xkagent_infra/groups/brain/projects/infrastructure
mkdir -p {service}/src

# 2. 复制源码（保留 Git 历史）
cp -r /xkagent_infra/brain/infrastructure/service/{service}/src/* {service}/src/

# 3. 创建 Makefile 和 project.yaml
# 从 brain_dashboard 复制模板并修改

# 4. 首次发布
make release VERSION=x.y.z
make deploy VERSION=x.y.z
make register VERSION=x.y.z
```

### 4. Infrastructure 端保留

```
/brain/infrastructure/service/{service}/
├── bin/                  # 启动脚本（保留）
├── current/              # 实际目录（由 deploy 创建）
├── releases/             # 实际目录（由 deploy 创建）
└── config/               # 运行时配置（保留）
```

## 依赖关系

```
agent_abilities
    ├── 被 brain_gateway 依赖
    ├── 被 brain_ipc 依赖

brain_ipc
    ├── 被 brain_agent_proxy 依赖
    ├── 被 brain_task_manager 依赖

brain_agent_proxy
    └── 被 agentctl 依赖
```

## 迁移顺序

按依赖顺序，从底层到上层：

1. **Phase 1: 基础服务**
   - agent_abilities
   - brain_ipc
   - brain_ipc_pty

2. **Phase 2: 中间层服务**
   - brain_gateway
   - brain_task_manager

3. **Phase 3: 上层服务**
   - brain_agent_proxy
   - brain_telegram_api
   - brain_google_api

## 风险与注意事项

1. **服务中断**: 迁移期间服务可能不可用
2. **配置路径**: supervisor 配置中的路径需要更新
3. **数据库**: 如果服务有数据库，需要确保路径正确
4. **测试**: 每个服务迁移后需要验证

## 当前状态

- ✅ brain_dashboard 已迁移
- ⏳ 其他服务待迁移
