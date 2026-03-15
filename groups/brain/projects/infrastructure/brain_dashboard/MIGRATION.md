# Brain Dashboard 迁移记录

## 迁移概述

按 `/brain/base/spec/standards/organization/file_organization.yaml` 规范，将 brain_dashboard 从 `infrastructure/service/` 迁移到 `groups/brain/projects/`。

## 迁移前结构

```
/xkagent_infra/brain/infrastructure/service/brain_dashboard/
├── current -> releases/v2.0.0/
├── releases/
│   ├── current -> v2.0.0/
│   ├── v1.0.0/
│   │   ├── src/
│   │   ├── bin/
│   └── v2.0.0/
│       ├── src/
│       ├── tests/
│       └── docs/
├── bin/
└── dashboard.db
```

## 迁移后结构

### 项目目录（源码）
```
/xkagent_infra/groups/brain/projects/brain_dashboard/
├── current -> releases/v2.0.0/
├── project.yaml              # 项目配置
├── src/                      # 源码（当前版本）
├── tests/                    # 测试
├── docs/                     # 文档
└── releases/
    ├── v1.0.0/              # 历史版本
    └── v2.0.0/              # 当前版本
```

### 运行时目录（部署入口）
```
/xkagent_infra/brain/infrastructure/service/brain_dashboard/
├── current -> /xkagent_infra/groups/brain/projects/brain_dashboard/current
├── releases/
│   ├── v1.0.0 -> /xkagent_infra/groups/brain/projects/brain_dashboard/releases/v1.0.0
│   └── v2.0.0 -> /xkagent_infra/groups/brain/projects/brain_dashboard/releases/v2.0.0
├── bin/                     # 启动脚本
└── dashboard.db             # 运行时数据库
```

## 软链接关系

```
# 项目中
current -> releases/v2.0.0/

# infrastructure 中
current -> /xkagent_infra/groups/brain/projects/brain_dashboard/current
releases/v1.0.0 -> /xkagent_infra/groups/brain/projects/brain_dashboard/releases/v1.0.0
releases/v2.0.0 -> /xkagent_infra/groups/brain/projects/brain_dashboard/releases/v2.0.0
```

## 迁移步骤

1. 创建新项目目录：`/xkagent_infra/groups/brain/projects/brain_dashboard/`
2. 复制当前版本源码：`releases/v2.0.0/{src,tests,docs}` → 项目根目录
3. 创建 `project.yaml` 项目配置文件
4. 迁移发布版本：`mv releases/ releases_deploy_backup/`
5. 在项目目录中恢复 releases 目录
6. 修复 infrastructure 软链接指向新项目
7. 清理旧位置冗余文件

## 验证命令

```bash
# 验证项目结构
ls -la /xkagent_infra/groups/brain/projects/brain_dashboard/

# 验证运行时入口
ls -la /xkagent_infra/brain/infrastructure/service/brain_dashboard/

# 验证软链接指向
ls -la $(readlink /xkagent_infra/groups/brain/projects/brain_dashboard/current)
ls -la $(readlink /xkagent_infra/brain/infrastructure/service/brain_dashboard/current)
```

## 迁移日期

2026-03-13

## 迁移执行者

agent-brain_manager
