# Brain Base 发布指南

适用范围：
- `/xkagent_infra/groups/brain/projects/base`
- `/xkagent_infra/brain/base`
- `/xkagent_infra/brain/infrastructure/config/agentctl`

目标：
- 说明 Brain Base 能力包如何从 project 源发布到 `brain/base`
- 说明哪些内容属于 `base` 发布，哪些属于运行时配置
- 说明发布后如何让 agent 真正吃到新能力

## 一、分层原则

### 1. 开发源与发布态分离

- 开发源：`/xkagent_infra/groups/brain/projects/base`
- 发布态：`/xkagent_infra/brain/base`

原则：
- 设计、修改、评审都在 `projects/base` 完成
- `brain/base` 只接收已整理、可复用、可发布的内容
- 禁止把 `brain/base` 当开发现场

### 2. base 发布与 runtime 配置分离

`base` 发布包含：
- `root files`：`index.yaml` / `INIT.md.new` / `README.md` / `PUBLISH_MANIFEST.yaml`
- `knowledge`
- `spec`
- `skill`
- `hooks`
- `scripts`
- `workflow`
- `mcp`
- 其他 `base` 域内容

不属于 `base` 发布的内容：
- `/xkagent_infra/brain/infrastructure/config/agentctl/*.yaml`
- 这类文件属于运行时配置，修改后需要 `agentctl apply-config/restart`

## 二、发布对象

### 1. base 根文件

通过同一脚本按 `root` 目标发布：

```bash
/xkagent_infra/groups/brain/projects/base/scripts/publish_base.sh --publish --domain root
```

包含：
- `index.yaml`
- `INIT.md.new`
- `README.md`
- `PUBLISH_MANIFEST.yaml`

### 2. base 域

由以下脚本统一发布：

```bash
/xkagent_infra/groups/brain/projects/base/scripts/publish_base.sh
```

支持域：
- `root`
- `knowledge`
- `spec`
- `skill`
- `hooks`
- `scripts`
- `workflow`
- `evolution`
- `mcp`

### 3. runtime 配置层

例如：
- `agents_registry.yaml`
- `skill_bindings.yaml`
- `lep_bindings.yaml`

这类文件不走 `publish_base.sh`，而是直接位于：

```bash
/xkagent_infra/brain/infrastructure/config/agentctl/
```

修改后通过以下动作生效：

```bash
agentctl apply-config <agents...> --apply
agentctl restart <agents...> --apply
```

## 三、标准发布流程

### Phase 1: 修改 project 源

在 `projects/base` 修改：
- `index.yaml`
- `INIT.md.new`
- `README.md`
- `PUBLISH_MANIFEST.yaml`
- `knowledge/*`
- `spec/*`
- `skill/*`
- `hooks/*`
- `scripts/*`
- `workflow/*`
- `mcp/*`

同时更新：
- 域内索引
- registry
- manifest / 说明文件

### Phase 2: 预演发布

先 dry-run：

```bash
/xkagent_infra/groups/brain/projects/base/scripts/publish_base.sh --dry-run --domain <domain>
```

典型示例：

```bash
/xkagent_infra/groups/brain/projects/base/scripts/publish_base.sh --dry-run --domain root
/xkagent_infra/groups/brain/projects/base/scripts/publish_base.sh --dry-run --domain skill
/xkagent_infra/groups/brain/projects/base/scripts/publish_base.sh --dry-run --domain hooks
/xkagent_infra/groups/brain/projects/base/scripts/publish_base.sh --dry-run --domain scripts
/xkagent_infra/groups/brain/projects/base/scripts/publish_base.sh --dry-run --domain spec
/xkagent_infra/groups/brain/projects/base/scripts/publish_base.sh --dry-run --domain mcp
```

### Phase 3: 正式发布

```bash
/xkagent_infra/groups/brain/projects/base/scripts/publish_base.sh --publish --domain <domain>
```

发布前脚本会自动备份旧目标到：

```bash
/xkagent_infra/groups/brain/projects/base/releases/publish_backups
```

补充：
- `--domain root` 会同步 `brain/base` 根文件，避免 `README.md` / `PUBLISH_MANIFEST.yaml` 再与 source 漂移
- `--domain mcp` 会先构建 `projects/base/mcp/brain_ipc_c`，再同步 `brain/base/mcp/`，最后刷新 `/brain/bin/brain_ipc_c_mcp_server` 和 `/brain/bin/mcp/mcp-brain_ipc_c`
- `--domain scripts` 会同步 `brain/base/scripts/`，确保 live 入口脚本不再和 source 漂移

### Phase 4: 运行时刷新

如果这次改动影响 agent 运行时消费链，例如：
- skill 绑定变化
- LEP 绑定变化
- hooks 行为变化
- settings.local.json/runtime manifest 注入变化

则必须继续执行：

```bash
agentctl apply-config <agents...> --apply
agentctl restart <agents...> --apply
```

## 四、发布后验证

至少验证四件事：

1. `brain/base` 目标文件已更新
2. registry/spec/guide 路径能对得上
3. 受影响 agent 的 `.claude/settings.local.json` 已刷新
4. 受影响 agent 的 `.brain/agent_runtime.json` 已刷新，并在 restart 后真正加载

建议检查：

```bash
agentctl online
```

以及：
- `settings.local.json`
- `agent_runtime.json`
- 相关 tmux pane 当前目录和模型

## 五、角色职责

### manager

负责：
- 判断这次变更属于 `base` 发布还是 runtime 配置变更
- 审核发布范围是否正确
- 决定是否需要同步 `apply-config/restart`

### devops

负责：
- 执行 dry-run / publish
- 执行 `apply-config` / `restart`
- 验证 agent 运行态与 hooks 生效状态
- 必要时回滚

## 六、常见错误

### 1. 只发布了 base，没有刷新 agent

表现：
- `brain/base` 文件已变
- agent 仍使用旧 skill / 旧 hooks / 旧 runtime prompt

原因：
- 少了 `apply-config + restart`

### 2. 把 runtime 配置误当成 base 发布物

表现：
- 改了 `skill_bindings.yaml` / `lep_bindings.yaml`
- 只执行 `publish_base.sh`
- agent 没有变化

原因：
- 运行时配置不走 `base` 发布

### 3. 直接手改 `brain/base`

表现：
- 临时看起来生效
- 下次 publish 被覆盖

原因：
- 违反“project 源 -> 发布态”的分层原则

## 七、快速命令

```bash
# 发布 root files
/xkagent_infra/groups/brain/projects/base/scripts/publish_base.sh --publish --domain root

# 发布单域
/xkagent_infra/groups/brain/projects/base/scripts/publish_base.sh --publish --domain skill

# 发布整个 base
/xkagent_infra/groups/brain/projects/base/scripts/publish_base.sh --publish

# 刷新 agent 配置
python3 /xkagent_infra/brain/infrastructure/service/agentctl/bin/agentctl \
  --config-dir /xkagent_infra/brain/infrastructure/config/agentctl \
  apply-config agent-brain_manager agent-system_devops --apply

# 重启 agent
python3 /xkagent_infra/brain/infrastructure/service/agentctl/bin/agentctl \
  --config-dir /xkagent_infra/brain/infrastructure/config/agentctl \
  restart agent-brain_manager agent-system_devops --apply
```
