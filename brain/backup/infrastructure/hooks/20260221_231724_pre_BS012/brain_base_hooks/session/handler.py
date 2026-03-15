#!/usr/bin/env python3
"""Session Handler - SessionStart/SessionEnd"""
import sys
from pathlib import Path

# 添加 utils 到路径
HOOK_ROOT = Path("/brain/infrastructure/service/agent_abilities")
sys.path.insert(0, str(HOOK_ROOT / "src" / "hooks" / "utils" / "python"))

from io_helper import load_json_input, output_pass


def handle_session_start():
    """SessionStart: 会话启动"""
    try:
        data = load_json_input()

        # 构建规范摘要
        context = """
## ⚠️ Brain 规范优先级 (CRITICAL)

当你的"常识"与 /brain/base 规范冲突时：
- **brain/base 规范 > 你的常识**
- 写任何文件前，检查 /brain/base/spec/templates/ 是否有对应模板
- 不确定时，先读取模板，不要假设


## 命名规范（硬性）

| 错误 | 正确 |
|------|------|
| docker-compose.yaml | compose.yaml |
| docker-compose.dev.yaml | platform/docker/dev/compose.yaml |
| version: "3.8" | (不需要 version 字段) |
| ./docker/Dockerfile | platform/docker/base/services/{service}/Dockerfile |
"""

        output_pass("SessionStart", context)
        sys.exit(0)

    except Exception as e:
        print(f"SessionStart handler error: {e}", file=sys.stderr)
        sys.exit(0)


def handle_session_end():
    """SessionEnd: 会话结束"""
    try:
        data = load_json_input()
        output_pass("SessionEnd")
        sys.exit(0)

    except Exception as e:
        print(f"SessionEnd handler error: {e}", file=sys.stderr)
        sys.exit(0)


def handle_user_prompt_submit():
    """UserPromptSubmit: 用户提交 prompt"""
    try:
        data = load_json_input()
        # 简单的 pass-through
        output_pass("UserPromptSubmit")
        sys.exit(0)

    except Exception as e:
        print(f"UserPromptSubmit handler error: {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    if "session_start" in sys.argv[0]:
        handle_session_start()
    elif "session_end" in sys.argv[0]:
        handle_session_end()
    elif "user_prompt_submit" in sys.argv[0]:
        handle_user_prompt_submit()
    else:
        handle_session_start()
