# Brain Base

该目录是 `/xkagent_infra/brain/base` 的完整开发镜像与发布源。

目标：
- 在 `projects/base` 侧统一维护 `brain/base` 全域内容
- 评审通过后再整体或按域发布到 `/xkagent_infra/brain/base`
- 不直接在 `brain/base/*` 中做日常开发

包含域：
- `evolution/`
- `hooks/`
- `knowledge/`
- `mcp/`
- `scripts/`
- `skill/`
- `spec/`
- `workflow/`

项目元数据：
- `project.yaml`
- `PUBLISH_MANIFEST.yaml`
- `releases/`

发布方式：
- 预演：`scripts/publish_base.sh --dry-run`
- 正式发布：`scripts/publish_base.sh --publish`
