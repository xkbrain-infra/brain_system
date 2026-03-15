# Sandbox 项目级扩展规范
# 路径: /xkagent_infra/groups/brain/platform/sandbox/PROJECT_EXTENSION.md

# Sandbox 项目级扩展指南

## 概述

项目可以在 Group 级 sandbox 平台基础上进行扩展和覆盖。

**核心原则**:
1. 继承 group 级 provider 和 template
2. 允许项目级覆盖（有限制）
3. 项目扩展持久化在项目目录

## 项目级配置路径

```
{xkagent_infra/groups/{group}/projects/{project}/
├── .sandbox/
│   ├── config.yaml          # 项目级 sandbox 配置
│   ├── Dockerfile           # 项目级 Dockerfile（可选，继承 base）
│   ├── compose.override.yaml # Compose 覆盖（可选）
│   └── hooks/               # 生命周期钩子
│       ├── pre-start.sh
│       ├── post-start.sh
│       ├── pre-stop.sh
│       └── post-stop.sh
```

## 配置覆盖规则

### 1. 可覆盖的配置

```yaml
# .sandbox/config.yaml
sandbox:
  # 扩展基础镜像
  base_image:
    extends: brain-sandbox-base:2.1.0
    add_packages:
      - redis-tools
      - postgresql-client

  # 额外环境变量
  environment:
    MY_SERVICE_URL: http://localhost:8080
    MY_DB_PATH: /workspace/data/app.db

  # 额外端口
  ports:
    - "${HOST_PORT_REDIS}:6379"

  # 额外卷挂载
  volumes:
    - type: bind
      source: ${PROJECT_ROOT}/data
      target: /workspace/data/custom

  # 项目级 provider 覆盖
  provider_overrides:
    docker:
      development:
        command: >
          bash -c "
            echo 'Custom dev start' &&
            python -m uvicorn app:app --reload --host 0.0.0.0 --port 8080
          "
```

### 2. 禁止覆盖的配置

以下配置 **禁止** 项目级覆盖（违反 LEP Gates）:

- 安全相关: `privileged`, `security_opt`, `cap_add`
- 敏感挂载: `/etc/ssh`, `/root/.ssh`, `/brain/base/*`
- 网络模式: 必须为 bridge
- 资源上限: 只能收紧，不能放宽
- 命名规范: 必须符合 `{group}-{project}-{type}-{id}`

### 3. Dockerfile 继承

项目可以创建自己的 Dockerfile，但必须继承 base:

```dockerfile
# projects/{project}/.sandbox/Dockerfile
FROM brain-sandbox-base:2.1.0

# 项目特定依赖
RUN pip install --no-cache-dir \
    my-custom-package \
    another-package

# 项目特定工具
RUN apt-get update && apt-get install -y \
    my-tool \
    && rm -rf /var/lib/apt/lists/*

# 项目环境变量
ENV MY_PROJECT_VAR=value

# 保持 base 的 entrypoint
CMD ["sleep", "infinity"]
```

## 生命周期钩子

项目可以定义自己的生命周期钩子:

```bash
#!/bin/bash
# .sandbox/hooks/post-start.sh

echo "Project-specific post-start hook"

# 初始化数据库
python -c "from app import init_db; init_db()"

# 启动额外服务
redis-server --daemonize yes

# 运行健康检查
curl -f http://localhost:8080/health || exit 1
```

钩子执行顺序:
1. Group 级 pre-start
2. Project 级 pre-start
3. 容器启动
4. Group 级 post-start
5. Project 级 post-start

## 多环境支持

一个项目可以有多个 sandbox 实例:

```yaml
# .sandbox/config.yaml
instances:
  dev-1:
    type: development
    ports:
      app: 18080
      debug: 18100

  dev-2:
    type: development
    ports:
      app: 18081
      debug: 18101

  test:
    type: testing
    auto_destroy: true
```

启动命令:
```bash
# 启动特定实例
sandbox start --instance dev-1

# 启动所有开发实例
sandbox start --type development
```

## 示例：brain_dashboard 项目扩展

```yaml
# /xkagent_infra/groups/brain/projects/infrastructure/brain_dashboard/.sandbox/config.yaml

sandbox:
  project: brain_dashboard
  group: brain

  base_image:
    extends: brain-sandbox-base:2.1.0
    add_packages:
      - sqlite3-tools

  environment:
    DASHBOARD_DATA: /workspace/data/dashboard.db
    DASHBOARD_PORT: 8080
    DASHBOARD_HOST: 0.0.0.0

  ports:
    - "${HOST_PORT}:8080"

  volumes:
    # 挂载 dashboard 数据库
    - type: volume
      source: dashboard_data
      target: /workspace/data

  provider_overrides:
    docker:
      development:
        command: >
          bash -c "
            cd /workspace/project/src &&
            python -m uvicorn app:app --reload --host 0.0.0.0 --port 8080
          "
      testing:
        command: >
          bash -c "
            cd /workspace/project &&
            pytest tests/ -v --cov=src --cov-report=xml &&
            echo 'Tests completed'
          "
```

## 持久化规则

| 数据类型 | 存储位置 | 持久化策略 |
|---------|---------|-----------|
| 项目源码 | host (bind mount) | 永久 |
| 数据库 | named volume | 按类型决定 |
| 日志 | named volume | 按类型决定 |
| 配置 | host (.sandbox/) | 永久 |
| 审计日志 | host (archives/) | 永久 |

### 清理策略

```yaml
# .sandbox/config.yaml
cleanup:
  development:
    on_stop: keep       # 停止后保留
    on_delete: archive  # 删除时归档
    max_age: "7d"       # 7天后清理

  testing:
    on_stop: delete     # 停止后删除
    on_delete: delete   # 直接删除

  audit:
    on_stop: archive    # 归档
    on_delete: archive  # 归档
    retention: "90d"    # 保留90天
```

## 验证

项目级配置必须经过验证:

```bash
# 验证配置
sandbox validate --project brain_dashboard

# 检查 LEP Gates
sandbox check-gates --project brain_dashboard --type development
```

## 迁移指南

如果项目已有自定义 Docker 设置，迁移步骤:

1. 移动配置到 `.sandbox/config.yaml`
2. 更新 Dockerfile 继承 base
3. 删除旧的 `deploy/` 目录
4. 运行验证: `sandbox validate`
