# Brain Infrastructure Projects

该目录存放会发布到 `/xkagent_infra/brain/infrastructure/*` 的开发源项目。

## 目录结构

```
/xkagent_infra/groups/brain/projects/infrastructure/
├── README.md
└── brain_dashboard/          # Brain Dashboard 监控服务
    ├── Makefile
    ├── project.yaml
    └── ...
```

## 约定

- 服务、运行时、代理、MCP、面板等基础设施项目优先在这里开发
- 发布目标为 `brain/infrastructure/*`
- 可逐步把现有平铺在 `projects/` 下的基础设施项目迁入本目录

## 发布规范

参考: `/xkagent_infra/groups/brain/spec/deployment/release_process.yaml`

```bash
# 在 brain_dashboard 目录
make all VERSION=2.2.0
```
