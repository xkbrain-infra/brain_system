# Audit Logger v1 - 变更日志

## v1.0.0 - 2026-02-13

### 新增
- ✅ 工具使用日志记录
- ✅ Hook 事件日志记录
- ✅ JSONL 格式输出
- ✅ 自动创建日志目录

### 功能
- `log_tool_use(hook_event, tool_name, tool_input)` - 记录工具使用
- `log_hook_event(hook_event, data)` - 记录 hook 事件
- 包含时间戳、agent、cwd 等上下文信息

### 日志位置
- `/brain/runtime/logs/hooks_audit.jsonl`

### 日志格式
```json
{
  "timestamp": "2026-02-13T18:00:00",
  "hook_event": "PreToolUse",
  "tool_name": "Write",
  "tool_input": {...},
  "cwd": "/brain",
  "agent": "agent_system_pmo"
}
```

### 特性
- 非阻塞：审计失败不影响操作
- 自动创建目录
- JSONL 格式易于分析

### 依赖
- Python 3.7+
- 标准库：json, os, datetime, pathlib
