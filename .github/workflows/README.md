# GitHub Actions Release Configuration

## 概述

GitHub Actions 工作流实现了完整的 CI/CD 发布流程，发布到 **GitHub Container Registry (ghcr.io)**。

## 工作流说明

### 1. release-brain-system.yml
**触发条件**:
- 推送 `v*` 标签 (如 `v2.1.0`)
- 手动触发 (workflow_dispatch)

**发布内容**:
- 构建并推送 `ghcr.io/xkbrain-infra/brain-system` 镜像
- 自动创建 GitHub Release
- 支持语义化版本标签

### 2. release-sandbox.yml
**触发条件**:
- 推送 `sandbox-v*` 标签
- 手动触发

**发布内容**:
- 构建 `ghcr.io/xkbrain-infra/brain-sandbox-base`
- 构建各环境变体: `dev`, `test`, `staging`, `audit`

### 3. nightly.yml
**触发条件**:
- 每天凌晨 2 点自动运行
- 手动触发

**发布内容**:
- 构建 nightly 版本的 brain-system 和 sandbox-base

## 使用方式

### 本地开发使用 GitHub 镜像

```bash
# 登录 GitHub Container Registry
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin

# 拉取发布版本
docker pull ghcr.io/xkbrain-infra/brain-system:2.1.0
docker pull ghcr.io/xkbrain-infra/brain-sandbox-base:2.1.0
docker pull ghcr.io/xkbrain-infra/brain-sandbox-dev:latest

# 使用特定版本
export BRAIN_IMAGE=ghcr.io/xkbrain-infra/brain-system
export BRAIN_VERSION=2.1.0

# 构建 sandbox
cd groups/brain/platform/sandbox/dev
docker build --build-arg BRAIN_IMAGE=$BRAIN_IMAGE --build-arg BRAIN_VERSION=$BRAIN_VERSION .
```

### 发布新版本

```bash
# 1. 更新版本号
cd groups/brain/platform/release
./release.sh version 2.2.0

# 2. 提交并打标签
git add .
git commit -m "Release brain-system v2.2.0"
git tag v2.2.0
git push origin main --tags

# 3. GitHub Actions 自动触发发布
```

### 手动触发工作流

1. 进入 GitHub 仓库页面
2. 点击 **Actions** 标签
3. 选择工作流 (如 "Release Brain System")
4. 点击 **Run workflow**
5. 输入版本号，点击运行

## 镜像命名规范

| 镜像 | 示例 |
|------|------|
| 基础镜像 | `ghcr.io/xkbrain-infra/brain-docker-base:latest` |
| Brain System | `ghcr.io/xkbrain-infra/brain-system:2.1.0` |
| Sandbox Base | `ghcr.io/xkbrain-infra/brain-sandbox-base:2.1.0` |
| Sandbox Dev | `ghcr.io/xkbrain-infra/brain-sandbox-dev:latest` |
| Sandbox Test | `ghcr.io/xkbrain-infra/brain-sandbox-test:latest` |
| Sandbox Staging | `ghcr.io/xkbrain-infra/brain-sandbox-staging:latest` |
| Sandbox Audit | `ghcr.io/xkbrain-infra/brain-sandbox-audit:latest` |

## 权限配置

确保 GitHub Actions 有权限推送镜像：

```yaml
permissions:
  contents: write      # 创建 Release
  packages: write      # 推送 Container 镜像
```

在个人访问令牌 (PAT) 中需要勾选:
- `read:packages`
- `write:packages`
- `delete:packages` (可选)

## 缓存优化

工作流使用 GitHub Actions 缓存加速构建:

```yaml
cache-from: type=gha
cache-to: type=gha,mode=max
```

## 版本策略

- **Latest**: 指向最新稳定版本
- **Major**: `2` 指向 2.x.x 最新版
- **Major.Minor**: `2.1` 指向 2.1.x 最新版
- **Full**: `2.1.0` 精确版本
- **Nightly**: `nightly` 每日构建

## 故障排查

### 镜像推送失败
1. 检查 `GITHUB_TOKEN` 权限
2. 确认仓库启用了 Packages 功能
3. 检查镜像名称是否正确

### 构建失败
1. 检查 Dockerfile 语法
2. 确认基础镜像存在
3. 查看 Actions 日志详情
