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
    """输出拦截消息 - 输出JSON block响应并以exit code 2阻止"""
    # Output JSON to stdout for contract compatibility (test checks hookSpecificOutput.block)
    output_json({
        "hookSpecificOutput": {
            "hookEventName": hook_event,
            "block": True,
            "blockMessage": message
        }
    })
    # Also exit with code 2 (Claude Code native block mechanism)
    sys.exit(2)


def output_warn(hook_event: str, message: str):
    """输出警告消息（不阻塞操作）"""
    output_json({
        "hookSpecificOutput": {
            "hookEventName": hook_event,
            "block": False,
            "warning": message
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
