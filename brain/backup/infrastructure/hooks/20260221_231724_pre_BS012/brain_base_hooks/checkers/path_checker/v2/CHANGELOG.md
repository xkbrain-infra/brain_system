# Path Checker v1 - 变更日志

## v1.0.0 - 2026-02-13

### 新增
- ✅ SPEC 路径验证功能
- ✅ Glob 模式匹配（支持 `*` 和 `**`）
- ✅ 禁止路径检查（forbidden_patterns）
- ✅ 允许路径检查（allowed_patterns）
- ✅ 规则从 YAML 文件加载

### 功能
- `check_spec_path(file_path, rules_yaml)` - 主检查函数
- `matches_pattern(path, pattern)` - Glob 模式匹配
- `is_forbidden(path, patterns)` - 禁止路径检查
- `is_allowed(path, patterns)` - 允许路径检查

### 支持的规则
- `**/.claude/plans/**` - 禁止 Claude CLI 默认计划目录
- `**/tmp/**` - 禁止临时目录
- `/root/**` - 禁止 root 用户目录
- `/brain/groups/**/spec/**` - 允许所有 group 的 spec 目录

### 测试
- ✅ 单元测试通过
- ✅ 集成测试通过
- ✅ 生产环境验证通过

### 已知限制
- 不支持复杂的正则表达式
- YAML 解析器较简单（避免依赖 pyyaml）

### 性能
- 平均检查时间：< 10ms
- 规则加载：< 5ms

### 依赖
- Python 3.7+
- 标准库：re, pathlib
