# Brain Dashboard 发布流程

## 规范

**规范 ID**: BRAIN-DEPLOY-001
**规范路径**: `/xkagent_infra/groups/brain/spec/deployment/release_process.yaml`

## 完整发布流程

### 1. 开发阶段

```bash
cd /xkagent_infra/groups/brain/projects/brain_dashboard

# 开发代码...

# 运行测试
make test

# 构建
make build
```

### 2. 发布流程

```bash
# 方式 1: 分步发布（推荐）
make release VERSION=2.2.0   # 创建新版本
make deploy VERSION=2.2.0    # 部署到 infrastructure（实际文件）
make register VERSION=2.2.0  # 更新 supervisor + agentctl 注册
make verify                  # 验证状态

# 方式 2: 一键发布
make all VERSION=2.2.0
```

### 3. 各阶段说明

#### make release
- 创建 `releases/v2.2.0/`
- 更新 `current` 软链接（groups 端）
- 更新 `project.yaml` 版本

#### make deploy（关键）
- 复制实际文件到 `infrastructure/service/`
- **禁止软链接**（BRAIN-DEPLOY-001）
- 备份 `current` 到 `.previous`
- 创建新的 `current` 目录（实际文件）

#### make register（服务注册）
- 更新 `supervisord.d/brain_dashboard.conf` 版本号
- 更新 `agents_registry.yaml` 版本号
- 重载 supervisor 配置

## 服务注册更新

### Supervisor 配置

**路径**: `/xkagent_infra/brain/infrastructure/config/supervisord.d/brain_dashboard.conf`

更新字段:
- 版本号注释
- `environment=DASHBOARD_VERSION="x.y.z"`
- `directory` 路径

### Agentctl 注册表

**路径**: `/xkagent_infra/brain/infrastructure/config/agentctl/agents_registry.yaml`

更新字段:
- `version: vx.y.z`
- `health.endpoint`（如有变更）
- `port`（如有变更）

### IPC 名称

**注意**: IPC 名称 `service-brain_dashboard` 通常保持不变。如需变更，需要额外协调。

## 验证命令

```bash
make verify-deploy     # 验证 infrastructure 是实际文件
make verify-register   # 验证服务注册
```

## 回滚

```bash
make rollback          # 从 .previous 恢复
```

## LEP Gates

### G-BRAIN-DEPLOY-REAL
- Infrastructure 必须是实际文件，禁止软链接指向 groups

### G-BRAIN-DEPLOY-REGISTER
- Supervisor 和 Agentctl 版本号必须与发布版本一致

## 目录结构

```
# Groups 源码端
/xkagent_infra/groups/brain/projects/brain_dashboard/
├── Makefile
├── project.yaml
├── current@ -> releases/vX.Y.Z/
├── src/
└── releases/
    ├── v2.0.0/
    ├── v2.1.0/
    └── v2.2.0/          # 新版本

# Infrastructure 运行时端
/xkagent_infra/brain/infrastructure/service/brain_dashboard/
├── bin/
├── current/              # 实际目录（非软链接！）
├── releases/
│   ├── v2.0.0/
│   ├── v2.1.0/
│   └── v2.2.0/          # 实际目录（非软链接！）
├── .previous/            # 备份
└── dashboard.db
```
