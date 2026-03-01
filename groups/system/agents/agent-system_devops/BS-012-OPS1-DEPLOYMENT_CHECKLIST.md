# BS-012-OPS1 部署检查清单
# Hooks v3.0.0 全量部署到所有 Agents

**任务编号**: BS-012-OPS1
**执行人**: agent_system_devops
**日期**: 2026-02-21
**状态**: 准备完成，待 PMO 批准执行

---

## 一、Pre-flight 检查结果

### 1.1 源文件验证 ✅

| 检查项 | 状态 | 详情 |
|--------|------|------|
| `/brain/base/hooks/` 目录存在 | ✅ | 由 brain-manager 部署，2026-02-21 22:50 |
| `pre_tool_use` 可执行 | ✅ | `-rwxr-xr-x`, MD5: `87b34de2fc6300ea2619085d50024c88` |
| `post_tool_use` 可执行 | ✅ | `-rwxr-xr-x` |
| `session_start` 可执行 | ✅ | `-rwxr-xr-x` |
| `session_end` 可执行 | ✅ | `-rwxr-xr-x` |
| `user_prompt_submit` 可执行 | ✅ | `-rwxr-xr-x` |
| LEP 引擎模块完整 | ✅ | `lep/`, `tool_validation/`, `session/`, `checkers/`, `utils/` |

### 1.2 功能测试结果 ✅

| 测试用例 | 输入 | 预期输出 | 实测结果 |
|----------|------|----------|----------|
| pre_tool_use 基本执行 | Bash 工具调用 | `hookSpecificOutput` JSON | ✅ 通过 |
| post_tool_use 基本执行 | 工具结果 | `hookSpecificOutput` JSON | ✅ 通过 |
| session_start 初始化 | SessionStart 事件 | 含规范提示的 context | ✅ 通过 |
| session_end 清理 | SessionEnd 事件 | `hookSpecificOutput` JSON | ✅ 通过 |
| LEP 路径拦截 | Write 到保护路径 | `block: true` | ✅ 通过（G-SCOP 触发） |

### 1.3 当前生产环境状态 ⚠️

**全部 23 个 Agent 均在旧版 hooks 上（需升级）**

| 组别 | Agent 数 | 版本状态 |
|------|----------|----------|
| brain_system | 11 | ⚠️ 全部旧版 |
| digital_resources | 3 | ⚠️ 全部旧版 |
| local-model-lab | 4 | ⚠️ 全部旧版 |
| xkquant | 5 | ⚠️ 全部旧版 |
| **合计** | **23** | **全部需升级** |

旧版路径：`/brain/infrastructure/service/agent_abilities/src/hooks/handlers/tool_validation/current/python`
（路径仍存在，旧版 hooks 当前可运行，但使用分散架构）

**注**: `/brain/.claude/hooks/` 已是新版（使用 symlinks），已验证。

---

## 二、备份信息

| 备份项 | 路径 | 状态 |
|--------|------|------|
| 备份目录 | `/brain/infrastructure/data/backups/hooks/20260221_231724_pre_BS012/` | ✅ 完成 |
| 备份内容 | 11个 brain_system agent hooks | ✅ 已备份 |
| brain root hooks | `backup/brain_root_hooks/` | ✅ 已备份 |
| brain base hooks | `backup/brain_base_hooks/` | ✅ 已备份 |

---

## 三、部署方案

### 3.1 部署策略

**使用 Symlink 方式**（替代原硬链接方案）

原因：
- Symlink 使得后续 `/brain/base/hooks/` 更新时自动生效，无需重新部署
- 与 `/brain/.claude/hooks/` 保持一致（已验证有效的模式）
- 更易于审计和验证

### 3.2 部署范围（BS-012 仅 brain_system 组）

**阶段一**（BS-012 范围）：brain_system 组 11 个 agents

```
/brain/groups/org/brain_system/agents/agent-brain-manager/
/brain/groups/org/brain_system/agents/agent_system_architect/
/brain/groups/org/brain_system/agents/agent_system_creator/
/brain/groups/org/brain_system/agents/agent_system_dev/
/brain/groups/org/brain_system/agents/agent_system_dev2/
/brain/groups/org/brain_system/agents/agent_system_dev3/
/brain/groups/org/brain_system/agents/agent_system_devops/
/brain/groups/org/brain_system/agents/agent_system_frontdesk/
/brain/groups/org/brain_system/agents/agent_system_pmo/
/brain/groups/org/brain_system/agents/agent_system_qa/
/brain/groups/org/brain_system/agents/agent_system_ui-designer/
```

**阶段二**（跨组，需各组 PMO 批准，超出本 ticket 范围）：
- digital_resources (3 agents)
- local-model-lab (4 agents)
- xkquant (5 agents)

### 3.3 每个 Agent 的部署操作

```bash
# 对每个 agent 执行以下操作：
AGENT_HOOKS_DIR="/brain/groups/org/brain_system/agents/{agent_name}/.claude/hooks"

# 替换为 symlinks（原子操作）
for hook in pre_tool_use post_tool_use session_start session_end user_prompt_submit; do
    # 删除旧硬链接，创建新 symlink
    ln -sf "/brain/base/hooks/$hook" "$AGENT_HOOKS_DIR/$hook"
done
```

### 3.4 部署顺序（灰度）

```
Step 1: agent_system_devops（自身，最低风险）→ 验证
Step 2: agent_system_qa → 验证
Step 3: 其余 9 个 agents（批量）
```

---

## 四、验证步骤

每个 Agent 升级后执行：

```bash
# 1. 确认 symlink 指向正确
ls -la {agent_hooks_dir}/

# 2. 验证目标文件可达
python3 {agent_hooks_dir}/pre_tool_use < /dev/null

# 3. MD5 验证（应等于 87b34de2fc6300ea2619085d50024c88）
md5sum {agent_hooks_dir}/pre_tool_use
```

---

## 五、回滚方案

**触发条件**: 任何 Agent 升级后出现 hooks 执行错误

**回滚步骤**:
```bash
# 从备份恢复
BACKUP="/brain/infrastructure/data/backups/hooks/20260221_231724_pre_BS012"
AGENT_NAME="{agent_name}"

cp -p "$BACKUP/agents/$AGENT_NAME/"* \
    "/brain/groups/org/brain_system/agents/$AGENT_NAME/.claude/hooks/"

# 验证恢复
md5sum "/brain/groups/org/brain_system/agents/$AGENT_NAME/.claude/hooks/pre_tool_use"
```

**回滚时间**: 预计 < 2 分钟（每 agent）

---

## 六、风险评估

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| Agent hooks 执行异常 | 低 | 功能测试已通过；备份已就绪 |
| 旧版路径依赖失效 | 低 | 部署后旧路径不再被依赖 |
| 多 agent 同时运行时部署 | 中 | 采用 ln -sf 原子操作，运行中 agent 不受影响（下次 session 生效） |
| 跨组 agent 版本不一致 | 低 | 阶段一仅 brain_system，跨组另行审批 |

**总体风险**: 低
**需要停机**: 否（运行中 agent 不中断，下次 session 加载新 hooks）

---

## 七、执行前置条件（待 PMO 确认）

- [ ] PMO 批准部署窗口
- [ ] 确认 brain_system 组 agents 当前无关键任务执行中
- [ ] setup_hooks.sh 更新（注：当前脚本引用的 `/brain/infrastructure/hooks/bin/current` 路径已不存在，需更新为使用 symlink 方案，或直接手动执行）

---

## 八、预计耗时

| 步骤 | 时间 |
|------|------|
| 灰度验证（devops + qa） | ~5 分钟 |
| 批量部署剩余 9 agents | ~5 分钟 |
| 验证全量 | ~5 分钟 |
| **总计** | **~15 分钟** |

---

*产出人: agent_system_devops*
*产出时间: 2026-02-21 23:17*
