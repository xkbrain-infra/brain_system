# agent_abilities 测试指南

> 本文件记录 `agent_abilities` 构建系统的测试方法，包括单元测试、结构性测试和集成测试。

---

## 测试体系总览

```
单元测试     → src/tests/hooks/          LEP engine / checkers 逻辑
结构性测试   → src/tests/base/spec/      registry 完整性、角色覆盖
集成测试     → 直接调用 hook 脚本        真实拦截行为验证
```

工作目录：`/brain/infrastructure/service/agent_abilities/`

---

## 1. 单元测试（hooks 引擎逻辑）

测试 LEP engine 的 pattern matching、checker 实现等纯 Python 逻辑。

```bash
python3 -m pytest src/tests/hooks/test_lep_engine.py \
                  src/tests/hooks/test_checkers.py -v
# 预期：31 passed
```

文件说明：

| 文件 | 覆盖内容 |
|------|----------|
| `test_lep_engine.py` | LepEngine 初始化、gate 匹配、优先级、错误处理 |
| `test_checkers.py` | InlineChecker、BinaryChecker、PathChecker、FileOrgChecker |

---

## 2. Spec 结构性测试

验证 spec 目录的一致性：registry 索引链、角色模板覆盖、quick_lookup 可达性。

```bash
python3 -m pytest src/tests/base/spec/ -v
# 预期：9 passed
```

文件说明：

| 文件 | 验证内容 |
|------|----------|
| `test_index_chain.py` | index.yaml → registry → categories → files 链路完整 |
| `test_role_coverage.py` | 各角色模板存在、quick_lookup 有对应条目、topic 可达 |

---

## 3. 集成测试（直接调用 hook 脚本）

向 hook 脚本 stdin 喂入 Claude Code 格式的 JSON，验证实际拦截行为。

```bash
HOOK="python3 bin/hooks/current/pre_tool_use"

# 合法操作 → exit=0, pass
echo '{"hookEventName":"PreToolUse","tool_name":"Write","tool_input":{"file_path":"/brain/groups/org/test.yaml"}}' | $HOOK

# 违规：tmux 操作 agent session → exit=2, blocked (G-AGENT-LIFECYCLE)
echo '{"hookEventName":"PreToolUse","tool_name":"Bash","tool_input":{"command":"tmux kill-session -t agent-system_pmo"}}' | $HOOK

# 违规：写 base/spec/core → exit=2, blocked (G-SCOP)
echo '{"hookEventName":"PreToolUse","tool_name":"Write","tool_input":{"file_path":"/brain/base/spec/core/lep.yaml"}}' | $HOOK

# 警告：删除操作未备份 → exit=0, warning (G-DELETE-BACKUP)
echo '{"hookEventName":"PreToolUse","tool_name":"Bash","tool_input":{"command":"rm -rf /brain/base"}}' | $HOOK
```

**退出码约定：**

| exit code | 含义 |
|-----------|------|
| 0 | pass 或 warning（操作允许） |
| 2 | block（操作被拦截） |

---

## 4. 一键跑全套测试

```bash
python3 -m pytest \
  src/tests/hooks/test_lep_engine.py \
  src/tests/hooks/test_checkers.py \
  src/tests/base/spec/ \
  -q
# 预期：40 passed
```

---

## 注意事项

- 单元测试依赖 `pytest`，系统无则 `pip install pytest --break-system-packages`
- hooks 集成测试必须从 `agent_abilities/` 根目录运行（`bin/hooks/current/` 是相对路径）
- `src/tests/hooks/venv_test/` 是旧 venv（路径已过期），不要用，直接用系统 `python3`
