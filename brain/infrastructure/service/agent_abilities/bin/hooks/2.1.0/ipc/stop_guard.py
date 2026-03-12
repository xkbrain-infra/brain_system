#!/usr/bin/env python3
"""Stop Hook Guard: 检查 IPC 队列，有消息时阻止 Agent 停止。

Claude Code Stop hook 格式：
  stdin:  {"stop_hook_active": true, ...}
  stdout: {"decision": "block", "reason": "..."} 或 exit(0) 表示放行
"""

import json
import os
import socket
import sys

DAEMON_SOCKET = os.environ.get("BRAIN_IPC_SOCKET", "/tmp/brain_ipc.sock")
AGENT_NAME = os.environ.get("BRAIN_AGENT_NAME", "")
MAX_CONSECUTIVE_BLOCKS = 10
COUNTER_FILE = f"/tmp/ipc_stop_guard_{AGENT_NAME}.count"


def peek_ipc_queue() -> int:
    """查询 IPC 队列中待处理消息数量（不出队）。"""
    if not AGENT_NAME:
        return 0
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(DAEMON_SOCKET)

        request = json.dumps({
            "action": "ipc_recv",
            "agent_name": AGENT_NAME,
            "count_only": True,
        }) + "\n"
        sock.sendall(request.encode())

        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break

        sock.close()
        resp = json.loads(data.decode().strip())
        return int(resp.get("count", 0))
    except Exception:
        return 0  # 异常时默认放行，不阻断 Agent


def read_counter() -> int:
    try:
        with open(COUNTER_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return 0


def write_counter(n: int) -> None:
    try:
        with open(COUNTER_FILE, "w") as f:
            f.write(str(n))
    except Exception:
        pass


def main() -> None:
    # 读取 Stop hook 输入（忽略内容，仅触发检查）
    try:
        json.load(sys.stdin)
    except Exception:
        pass

    # 安全阀：连续拦截超过上限，强制放行，防止消息处理异常导致死循环
    counter = read_counter()
    if counter >= MAX_CONSECUTIVE_BLOCKS:
        write_counter(0)
        sys.exit(0)

    pending = peek_ipc_queue()

    if pending > 0:
        write_counter(counter + 1)
        print(json.dumps({
            "decision": "block",
            "reason": (
                f"[IPC] 你有 {pending} 条待处理消息。"
                "请调用 ipc_recv() 获取并处理这些消息。"
            ),
        }, ensure_ascii=False))
    else:
        write_counter(0)
        sys.exit(0)  # 无消息，放行


if __name__ == "__main__":
    main()
