# Runtime Env Source Registry

此目录是 Brain 运行时环境变量的持久化“配置源索引”。

- 索引文件：`index.yaml`
- 密钥/凭据实际文件：仍存放在 `/brain/secrets/`
- 渲染输出：`/xkagent_infra/runtime/config/`

职责边界：

- `infrastructure/config/runtime_env/index.yaml`
  定义要加载哪些分类、哪些文件、哪些 env vars
- `/brain/secrets/**`
  存放真实 secret payload
- `/xkagent_infra/runtime/config/**`
  存放启动时生成的 `.env`、`sources.yaml`、`loaded_at.txt`

迁移说明：

- 新增或调整环境变量来源时，只修改这里的 `index.yaml`
- 不要把真实密钥直接写入本目录
