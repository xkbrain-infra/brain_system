# Session

- **Project**: brain-docker
- **Group**: brain
- **Path**: /xkagent_infra/groups/brain/platform/docker
- **Sandbox Mode**: read_only (infrastructure project, no sandbox needed)
- **Started**: 2026-03-15
- **Goal**: 迁移 brain/platform/docker 到三域架构模式 (source → runtime → published)

## 迁移任务清单

- [x] 创建项目目录结构
- [x] 迁移源代码到 src/
- [x] 迁移配置到 configs/
- [x] 迁移脚本到 scripts/
- [x] 迁移运行时数据到 app/brain/docker/
- [x] 创建项目元数据 (README.md, session.md, index.yaml)
- [x] 设置发布配置
- [x] 清理旧位置
- [x] 验证迁移完成

## 验证结果

### 旧位置清理
- `/xkagent_infra/brain/platform/docker/` 已清空（仅保留空目录结构）

### 三域架构验证

**Source 域** (`/xkagent_infra/groups/brain/platform/docker/`):
```
├── README.md
├── index.yaml
├── session.md
├── configs/      # .env, sshd_config, supervisord.conf
├── scripts/      # build.sh, start.sh, stop.sh
├── spec/         # 项目规范文档
└── src/          # Dockerfile, compose.yaml, services/
```

**Runtime 域** (`/xkagent_infra/app/brain/docker/`):
```
├── builds/       # 构建产物
├── data/         # 运行时数据 (含 docker-data/root/)
└── logs/         # 日志文件
```

**Published 域** (`/xkagent_infra/brain/platform/docker/`):
```
├── compose.yaml     # Docker Compose 配置（已更新路径）
├── Dockerfile       # 镜像构建文件
├── configs/         # 运行时配置（sshd_config, supervisord.conf）
├── scripts/         # 运维脚本（bootstrap, healthcheck, startup 等）
├── services/        # 子服务（brain-spec, service-registry）
├── images/          # Docker 镜像导出
└── manifests/       # 发布清单
```

**Published 域验证**:
- ✅ compose.yaml 路径已更新（context: ., dockerfile: Dockerfile）
- ✅ 可从 Published 域直接运行：`docker compose up -d`
- ✅ 无需引用 Source 域即可独立部署

### 状态
**迁移完成！** brain-docker 项目已正确遵循 Brain 三域架构模式。

**清理的旧位置:**
- `/xkagent_infra/groups/brain/projects/brain-docker/` - 已删除
- `/xkagent_infra/app/brain-docker/` - 已删除

## 相关路径

- **Old Location**: `/xkagent_infra/brain/platform/docker/`
- **Source**: `/xkagent_infra/groups/brain/platform/docker/`
- **Runtime**: `/xkagent_infra/app/brain/docker/`
- **Published**: `/xkagent_infra/brain/platform/docker/`
