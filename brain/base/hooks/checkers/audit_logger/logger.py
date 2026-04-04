#!/usr/bin/env python3
"""
审计日志器 - 记录所有 hook 操作

功能：
- 记录工具使用（PreToolUse/PostToolUse）
- 记录 hook 事件
- JSONL 格式，易于分析
- 支持从 lep.yaml 读取配置（dual_write 路径）
- 支持多目标写入（hooks, global）
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

# 默认日志路径（fallback）
LOG_DIR = Path("/xkagent_infra/runtime/logs")
AUDIT_LOG = LOG_DIR / "hooks_audit.jsonl"

# 尝试导入 lep 模块
try:
    LEP_MODULE_PATH = Path(__file__).parent.parent.parent.parent.parent / "lep"
    sys.path.insert(0, str(LEP_MODULE_PATH))
    from lep import load_lep
    _LEP_AVAILABLE = True
except ImportError:
    _LEP_AVAILABLE = False

# 缓存配置
_AUDIT_CONFIG = None


def _infer_agent_name() -> str:
    agent_name = os.environ.get("BRAIN_AGENT_NAME", "").strip()
    if agent_name:
        return agent_name

    cwd = Path.cwd().resolve()
    parts = cwd.parts
    if "agents" in parts:
        idx = parts.index("agents")
        if idx + 1 < len(parts):
            return parts[idx + 1]

    return "unknown"


def load_audit_config() -> Dict[str, Any]:
    """
    从 lep.yaml 加载 G-AUDIT 配置

    返回默认配置（如果 lep.yaml 不可用）
    """
    global _AUDIT_CONFIG
    if _AUDIT_CONFIG is not None:
        return _AUDIT_CONFIG

    # 默认配置（fallback）
    default_config = {
        'dual_write': {
            'hooks': str(AUDIT_LOG),
        },
        'config': {
            'block_on_failure': False,
            'max_entry_size': 10240,
        },
        'redact_fields': ['password', 'token', 'secret', 'api_key', 'credential'],
    }

    if not _LEP_AVAILABLE:
        _AUDIT_CONFIG = default_config
        return _AUDIT_CONFIG

    try:
        lep = load_lep()
        gate = lep.gates.get('G-AUDIT')

        if not gate or 'enforcement' not in gate:
            _AUDIT_CONFIG = default_config
            return _AUDIT_CONFIG

        enforcement = gate['enforcement']

        # 提取配置
        _AUDIT_CONFIG = {
            'dual_write': enforcement.get('dual_write', {}),
            'config': enforcement.get('config', {}),
            'redact_fields': enforcement.get('redact_fields', []),
        }

        # 如果 dual_write 为空，使用默认
        if not _AUDIT_CONFIG['dual_write']:
            _AUDIT_CONFIG['dual_write'] = default_config['dual_write']

        return _AUDIT_CONFIG

    except Exception as e:
        # 加载失败，使用默认配置
        _AUDIT_CONFIG = default_config
        return _AUDIT_CONFIG


def ensure_log_dir():
    """确保日志目录存在"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def redact_sensitive_data(data: Dict[str, Any], redact_fields: List[str]) -> Dict[str, Any]:
    """脱敏敏感字段"""
    if not redact_fields:
        return data

    result = {}
    for key, value in data.items():
        # 检查键名是否包含敏感词
        is_sensitive = any(field.lower() in key.lower() for field in redact_fields)

        if is_sensitive:
            result[key] = "***REDACTED***"
        elif isinstance(value, dict):
            result[key] = redact_sensitive_data(value, redact_fields)
        else:
            result[key] = value

    return result


def write_log_entry(log_path: str, entry: Dict[str, Any], max_size: int = 10240):
    """
    写入单条日志

    Args:
        log_path: 日志文件路径（支持 {date} 占位符）
        entry: 日志条目
        max_size: 单条日志最大大小（字节）
    """
    try:
        # 替换 {date} 占位符
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_path = log_path.replace("{date}", date_str)

        # 确保目录存在
        log_file = Path(log_path)
        log_file.parent.mkdir(parents=True, exist_ok=True)

        # 序列化
        log_line = json.dumps(entry, ensure_ascii=False)

        # 检查大小限制
        if len(log_line) > max_size:
            # 截断大的 tool_input
            if 'tool_input' in entry:
                entry_copy = entry.copy()
                entry_copy['tool_input'] = f"<truncated, size={len(str(entry['tool_input']))}>"
                log_line = json.dumps(entry_copy, ensure_ascii=False)

        # 写入
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_line + "\n")

    except Exception as e:
        # 审计失败不应阻止操作，静默忽略
        pass


def log_tool_use(
    hook_event: str,
    tool_name: str,
    tool_input: Dict[str, Any],
    blocked: bool = False,
    warned: bool = False,
    gate: str | None = None,
):
    """
    记录工具使用（支持 dual_write）

    从 lep.yaml (G-AUDIT.enforcement) 读取配置，写入多个目标
    """
    try:
        # 加载配置
        config = load_audit_config()

        # 构建日志条目
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "hook_event": hook_event,
            "tool_name": tool_name,
            "tool_input": tool_input,
            "blocked": blocked,
            "warned": warned,
            "gate": gate,
            "cwd": os.getcwd(),
            "user": os.environ.get("USER", "unknown"),
            "agent": _infer_agent_name(),
        }

        # 脱敏敏感字段
        redact_fields = config.get('redact_fields', [])
        if redact_fields:
            log_entry = redact_sensitive_data(log_entry, redact_fields)

        # 获取大小限制
        max_size = config.get('config', {}).get('max_entry_size', 10240)

        # Dual write - 写入所有配置的目标
        dual_write = config.get('dual_write', {})

        # 1. hooks 日志（主日志）
        if 'hooks' in dual_write:
            write_log_entry(dual_write['hooks'], log_entry, max_size)

        # 2. global 日志（所有 agent 操作）
        if 'global' in dual_write:
            write_log_entry(dual_write['global'], log_entry, max_size)

        # 3. project 日志（特定项目，可选）
        if 'project' in dual_write:
            # TODO: 从当前路径或环境变量推断 group/project
            # 暂时跳过，因为需要更多上下文信息
            pass

    except Exception as e:
        # 审计失败不应阻止操作
        pass


def log_hook_event(hook_event: str, data: Dict[str, Any]):
    """
    记录 hook 事件（支持 dual_write）
    """
    try:
        # 加载配置
        config = load_audit_config()

        # 构建日志条目
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "hook_event": hook_event,
            "data": data,
            "cwd": os.getcwd(),
            "agent": os.environ.get("BRAIN_AGENT_NAME", "unknown"),
        }

        # 脱敏
        redact_fields = config.get('redact_fields', [])
        if redact_fields:
            log_entry = redact_sensitive_data(log_entry, redact_fields)

        # 大小限制
        max_size = config.get('config', {}).get('max_entry_size', 10240)

        # Dual write
        dual_write = config.get('dual_write', {})

        if 'hooks' in dual_write:
            write_log_entry(dual_write['hooks'], log_entry, max_size)

        if 'global' in dual_write:
            write_log_entry(dual_write['global'], log_entry, max_size)

    except Exception:
        pass
