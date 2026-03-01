# Hooks Rules 目录

## ⚠️ 重要变更

**日期**: 2026-02-13

此目录中的规则文件已废弃，规则已迁移到统一配置文件：

```
/brain/base/spec/core/lep.yaml
```

## 迁移状态

### Deprecated Files

| 文件 | 状态 | 迁移目标 | 删除计划 |
|------|------|---------|---------|
| `spec_path.yaml` | ⚠️ DEPRECATED | `lep.yaml` (G-SPEC-LOCATION) | 2026-02-15 |

### 为什么迁移？

**问题**:
- 规则分散在多个文件（lep.yaml, spec_path.yaml）
- 重复定义导致维护困难
- 规则来源不清晰

**解决方案**:
- 统一规则源：`/brain/base/spec/core/lep.yaml`
- 每个 gate 包含完整的 enforcement 配置
- 配置驱动的检查逻辑

## 使用指南

### ✅ 正确方式（新代码）

```python
from checker import check_spec_path

# 不传 rules_yaml 参数，自动从 lep.yaml 读取
is_valid, error_msg = check_spec_path(file_path)
```

### ⚠️ 兼容方式（旧代码）

```python
from checker import check_spec_path
from pathlib import Path

# 传 rules_yaml 作为 fallback
rules_file = Path("/brain/infrastructure/service/agent_abilities/hooks/rules/spec_path.yaml")
is_valid, error_msg = check_spec_path(file_path, rules_file)
```

**注意**: fallback 机制仅用于兼容性，将在删除 spec_path.yaml 后失效。

## 迁移时间线

- **2026-02-13**: 规则迁移到 lep.yaml，spec_path.yaml 标记 deprecated
- **2026-02-13 ~ 2026-02-15**: 48h 监控期，两种方式并存
- **2026-02-15**: 删除 spec_path.yaml（如无问题）

## 验证方法

### 查看规则来源

检查错误消息中的 "规则来源" 字段：

```
🚫 SPEC 路径违规 (G-SPEC-LOCATION)
...
规则来源: lep.yaml  ← 应该是 lep.yaml
```

如果显示 `spec_path.yaml` 或其他路径，说明 lep.yaml 加载失败，请检查：
1. `/brain/base/spec/core/lep.yaml` 是否存在
2. `G-SPEC-LOCATION` gate 是否包含 enforcement 配置
3. lep 模块是否正确加载

### 测试

```bash
cd /brain/infrastructure/service/agent_abilities/hooks
bash scripts/test_hooks.sh
```

## 问题排查

### 如果看到 "规则来源: spec_path.yaml"

说明 fallback 机制生效，可能原因：
1. lep.yaml 不存在或格式错误
2. G-SPEC-LOCATION 缺少 enforcement 配置
3. lep 模块导入失败

**解决方法**: 检查 stderr 中的警告信息

### 如果看到 "规则来源: none (default allow)"

说明两个规则文件都加载失败，所有路径都被允许（不安全）。

**解决方法**: 紧急恢复 spec_path.yaml 或修复 lep.yaml

---

**维护者**: Brain System Team
**最后更新**: 2026-02-13
