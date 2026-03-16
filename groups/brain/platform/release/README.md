# Brain System Release

Brain System 的发布打包系统，支持版本控制、镜像构建和发布管理。

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│                     Sandbox (dev/test/staging/audit)        │
│                         FROM brain/sandbox-base:2.1.0       │
└─────────────────────────┬───────────────────────────────────┘
                          │ depends on
┌─────────────────────────▼───────────────────────────────────┐
│                     Brain Sandbox Base                      │
│                         FROM brain/system:2.1.0             │
└─────────────────────────┬───────────────────────────────────┘
                          │ depends on
┌─────────────────────────▼───────────────────────────────────┐
│                     Brain System                            │
│                         FROM brain/docker-base:latest       │
│  包含:                                                      │
│  - /brain/base (specs, knowledge, templates)                │
│  - /brain/infrastructure (launch, hooks, mcp, ipc)          │
│  - /brain/platform/bin (utilities)                          │
│  - /brain/runtime (config templates)                        │
└─────────────────────────┬───────────────────────────────────┘
                          │ depends on
┌─────────────────────────▼───────────────────────────────────┐
│                     Brain Docker Base                       │
│                         FROM ubuntu:24.04                   │
│  包含: 系统工具, Python, Node.js, AI CLI tools, supervisor  │
└─────────────────────────────────────────────────────────────┘
```

## 目录结构

```
/xkagent_infra/groups/brain/platform/release/
├── VERSION                      # 当前版本号
├── release.sh                   # 发布管理主脚本
├── README.md                    # 本文档
├── configs/
│   ├── release.yaml            # 发布配置
│   └── Dockerfile.release      # brain/system 镜像 Dockerfile
├── scripts/
│   ├── build.sh                # 构建脚本
│   ├── publish.sh              # 发布脚本
│   ├── container-entrypoint.sh # 容器入口脚本
│   ├── validate.sh             # 验证脚本
│   └── ghcr.sh                 # GitHub Container Registry 助手
└── packages/                   # 构建产物
    ├── brain-system-2.1.0.tar.gz
    └── manifest-2.1.0.yaml
```

## 使用流程

### 1. 本地开发构建

```bash
cd /xkagent_infra/groups/brain/platform/release

# 验证系统
./scripts/validate.sh

# 构建当前版本
./release.sh build

# 构建指定版本
./release.sh build 2.2.0

# 发布到本地 registry
./release.sh publish
```

### 2. GitHub Actions 自动发布（推荐）

#### 发布新版本到 GitHub Container Registry

```bash
# 1. 更新版本号并提交
cd /xkagent_infra/groups/brain/platform/release
./release.sh version 2.2.0
git add VERSION
git commit -m "Bump version to 2.2.0"

# 2. 打标签并推送
git tag v2.2.0
git push origin main --tags
```

GitHub Actions 会自动：
- 构建 `ghcr.io/xkbrain-infra/brain-system:2.2.0`
- 创建 GitHub Release
- 推送镜像到 GitHub Container Registry

#### 使用 GitHub 发布的镜像

```bash
# 登录 GitHub Container Registry
./scripts/ghcr.sh login

# 拉取发布版本
./scripts/ghcr.sh pull brain-system 2.2.0
./scripts/ghcr.sh pull brain-sandbox-dev latest

# 切换到使用 GitHub 镜像
./scripts/ghcr.sh use-ghcr

# 切换回本地镜像
./scripts/ghcr.sh use-local

# 查看配置状态
./scripts/ghcr.sh status
```

### 3. 手动触发工作流

1. 打开 GitHub 仓库页面
2. 点击 **Actions** 标签
3. 选择 "Release Brain System"
4. 点击 **Run workflow**
5. 输入版本号，点击运行

## GitHub Container Registry 镜像

| 镜像 | 用途 |
|------|------|
| `ghcr.io/xkbrain-infra/brain-system:2.1.0` | Brain System 发布版本 |
| `ghcr.io/xkbrain-infra/brain-sandbox-base:2.1.0` | Sandbox 基础镜像 |
| `ghcr.io/xkbrain-infra/brain-sandbox-dev:latest` | 开发环境 |
| `ghcr.io/xkbrain-infra/brain-sandbox-test:latest` | 测试环境 |
| `ghcr.io/xkbrain-infra/brain-sandbox-staging:latest` | 预发布环境 |
| `ghcr.io/xkbrain-infra/brain-sandbox-audit:latest` | 审计环境 |

## 版本规范

遵循 [语义化版本规范](https://semver.org/lang/zh-CN/):

- **MAJOR**: 不兼容的 API 修改
- **MINOR**: 向下兼容的功能新增
- **PATCH**: 向下兼容的问题修复

格式: `MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]`

示例: `2.1.0`, `2.1.0-beta.1`, `2.1.0+build.123`

## 发布配置

配置文件: `configs/release.yaml`

可以自定义：
- 包含的组件
- 排除的文件模式
- 镜像名称和标签
- 发布目标 registry

## Sandbox 集成

Sandbox 通过 `brain/sandbox-base` 镜像消费 brain 发布版本：

```dockerfile
# sandbox/base/Dockerfile
ARG BRAIN_VERSION=2.1.0
FROM brain/system:${BRAIN_VERSION}
# ...
```

环境变量继承：
- `BRAIN_PATH=/brain` - Brain 系统路径
- `BRAIN_GROUPS=/groups` - Groups 路径
- `BRAIN_INFRA=/brain/infrastructure` - 基础设施路径

## 依赖关系

1. **brain/docker-base**: 基础系统镜像
2. **brain/system**: Brain 系统发布版本（依赖 brain/docker-base）
3. **brain/sandbox-base**: Sandbox 基础镜像（依赖 brain/system）
4. **brain/sandbox-dev/test/staging/audit**: 各环境 Sandbox（依赖 brain/sandbox-base）

## GitHub Actions 工作流

### release-brain-system.yml
- 触发: 推送 `v*` 标签 或手动触发
- 发布: `ghcr.io/xkbrain-infra/brain-system`

### release-sandbox.yml
- 触发: 推送 `sandbox-v*` 标签 或手动触发
- 发布: Sandbox 各环境镜像

### nightly.yml
- 触发: 每天凌晨 2 点
- 发布: Nightly 构建版本

详细说明: [GitHub Actions 文档](/.github/workflows/README.md)

## 命令参考

```bash
# 发布管理
./release.sh build [version]     # 构建发布版本
./release.sh publish [version]   # 发布到 registry
./release.sh version <version>   # 更新版本号
./release.sh list                # 列出发布历史
./release.sh clean               # 清理构建产物

# GitHub Container Registry
./scripts/ghcr.sh login          # 登录 ghcr.io
./scripts/ghcr.sh pull <image> [version]  # 拉取镜像
./scripts/ghcr.sh use-ghcr       # 使用 GitHub 镜像
./scripts/ghcr.sh use-local      # 使用本地镜像
./scripts/ghcr.sh status         # 查看状态
```
