# Agent Auth Bootstrap Setup

## 目标

Docker 部署后，支持手动执行引导初始化：
1. 从 secrets 同步 Claude/Codex/Gemini 登录态到 `/root`。
2. 执行 agent 配置生成（`apply-config --all --apply --force`）。
3. 启动并检查 agent 在线状态。

引导脚本：
- `/xkagent_infra/brain/platform/docker/scripts/agent_login_init.sh`

当前行为：
- 不再在 SSH 登录时自动触发
- 需要手动执行引导脚本

## 登录态文件放置路径（secrets）

将真实登录态文件放在以下路径：

- Claude:
  - source: `/xkagent_infra/brain/secrets/system/agents/auth/claude/.claude.json`
  - target: `/root/.claude.json`

- Codex:
  - source: `/xkagent_infra/brain/secrets/system/agents/auth/codex/auth.json`
  - target: `/root/.codex/auth.json`

- Gemini:
  - source: `/xkagent_infra/brain/secrets/system/agents/auth/gemini/oauth_creds.json`
  - target: `/root/.gemini/oauth_creds.json`
  - source: `/xkagent_infra/brain/secrets/system/agents/auth/gemini/google_accounts.json`
  - target: `/root/.gemini/google_accounts.json`
  - source: `/xkagent_infra/brain/secrets/system/agents/auth/gemini/installation_id`
  - target: `/root/.gemini/installation_id`
  - source: `/xkagent_infra/brain/secrets/system/agents/auth/gemini/state.json`
  - target: `/root/.gemini/state.json`

说明：
1. 缺哪个文件就提示哪个，不会阻塞 shell 登录。
2. 同步后的目标文件权限会被设置为 `600`。
3. secrets 目录下真实登录态文件不会提交到 git。

## 手动执行

- 仅同步登录态：
```bash
/xkagent_infra/brain/platform/docker/scripts/container_bootstrap.sh --agent-auth-only
```

- 强制重跑完整登录引导：
```bash
/xkagent_infra/brain/platform/docker/scripts/agent_login_init.sh --force
```

- 清理旧的登录 hook（如历史容器已注入）：
```bash
/xkagent_infra/brain/platform/docker/scripts/container_bootstrap.sh --ensure-login-hook
```
