#!/usr/bin/env python3
"""IO Helper - JSON 输入输出辅助函数"""
import json
import sys
from typing import Dict, Any


def load_json_input() -> Dict[str, Any]:
    """从 stdin 加载 JSON 输入"""
    try:
        return json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "Error",
                "error": f"Invalid JSON input: {e}"
            }
        }), file=sys.stderr)
        sys.exit(1)


def output_json(data: Dict[str, Any]):
    """输出 JSON 到 stdout"""
    print(json.dumps(data, ensure_ascii=False))


def output_block(hook_event: str, message: str):
    """输出拦截消息 - Claude Code 2.1.50+ 格式

    Claude Code 识别的 block 方式:
    1. hookSpecificOutput.permissionDecision = "deny" (PreToolUse 推荐)
    2. decision = "block" (通用, deprecated for PreToolUse)
    3. exit code 2 + stderr (硬拦截)

    我们同时使用 permissionDecision + exit code 2 确保拦截生效。
    """
    # 写 reason 到 stderr (exit code 2 时 Claude Code 用 stderr 作为错误消息)
    print(message, file=sys.stderr)
    # JSON stdout: permissionDecision=deny 是 PreToolUse 的标准格式
    output_json({
        "hookSpecificOutput": {
            "hookEventName": hook_event,
            "permissionDecision": "deny",
            "permissionDecisionReason": message
        }
    })
    sys.exit(2)


def output_warn(hook_event: str, message: str):
    """输出警告消息（不阻塞操作, Claude Code 显示为 notification）"""
    # 写到 stderr 让 Claude Code 显示警告
    print(message, file=sys.stderr)
    output_json({
        "hookSpecificOutput": {
            "hookEventName": hook_event,
            "permissionDecision": "allow",
            "permissionDecisionReason": message
        }
    })


def output_pass(hook_event: str, additional_context: str = None):
    """输出通过消息"""
    result = {
        "hookSpecificOutput": {
            "hookEventName": hook_event
        }
    }
    if additional_context:
        result["hookSpecificOutput"]["additionalContext"] = additional_context
    output_json(result)
