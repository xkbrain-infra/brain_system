#!/usr/bin/env python3
"""
orchestrator_driver.py — Project Orchestrator 守护驱动
=======================================================
职责：
  - 确保 orchestrator Claude session 持续在线（由 supervisor 管理本进程）
  - 启动后等待 orchestrator 上线，发送 ORCHESTRATOR_INIT 事件
  - 定期发送 HEARTBEAT 唤醒 orchestrator 检查 stale tasks
  - 检测 orchestrator 离线时，通过 agentctl 重启，并发送 RECOVERING 事件

本进程不做任何决策。所有项目决策由 orchestrator Claude session 负责。

部署位置（sandbox 内）:
  /workspace/runtime/agents/{ORCHESTRATOR_ID}/driver.py

Supervisor 配置示例:
  [program:orchestrator_driver]
  command=python3 /workspace/runtime/agents/%(ENV_ORCHESTRATOR_ID)s/driver.py
  autostart=true
  autorestart=true
  stdout_logfile=/workspace/logs/orchestrator_driver.log
  stderr_logfile=/workspace/logs/orchestrator_driver.err

环境变量（必须）:
  ORCHESTRATOR_ID      — orchestrator agent 的 agent_id
  PROJECT_ID           — 项目 ID
  SANDBOX_ID           — sandbox 实例 ID
  BRAIN_IPC_SOCKET     — IPC socket 路径（默认 /tmp/brain_ipc.sock）

环境变量（可选）:
  AGENTCTL_BIN         — agentctl 二进制路径（默认从 PATH 查找）
  HEARTBEAT_INTERVAL   — 心跳间隔秒数（默认 60）
  ONLINE_TIMEOUT       — 等待上线超时秒数（默认 120）
  MAX_RESTART_ATTEMPTS — 最大连续重启次数（默认 3）
"""

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

# ─── 配置 ────────────────────────────────────────────────────────────────────

ORCHESTRATOR_ID = os.environ.get("ORCHESTRATOR_ID", "")
PROJECT_ID = os.environ.get("PROJECT_ID", "")
SANDBOX_ID = os.environ.get("SANDBOX_ID", "")
IPC_SOCKET = os.environ.get("BRAIN_IPC_SOCKET", "/tmp/brain_ipc.sock")
AGENTCTL_BIN = os.environ.get("AGENTCTL_BIN", "agentctl")
HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", "60"))
ONLINE_TIMEOUT = int(os.environ.get("ONLINE_TIMEOUT", "120"))
MAX_RESTART_ATTEMPTS = int(os.environ.get("MAX_RESTART_ATTEMPTS", "3"))

LOG_PATH = Path(f"/workspace/logs/orchestrator_driver.log")

# ─── 日志 ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [driver] %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ],
)
log = logging.getLogger("orchestrator_driver")


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def _run(cmd: list[str], check: bool = False, capture: bool = True) -> subprocess.CompletedProcess:
    """执行命令，失败时记录日志但不抛出（除非 check=True）"""
    try:
        return subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            timeout=30,
            check=check,
        )
    except subprocess.TimeoutExpired:
        log.warning("命令超时: %s", " ".join(cmd))
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="timeout")
    except FileNotFoundError:
        log.error("命令不存在: %s", cmd[0])
        return subprocess.CompletedProcess(cmd, returncode=127, stdout="", stderr="not found")


def is_online() -> bool:
    """检查 orchestrator 是否在 agentctl online 列表中"""
    result = _run([AGENTCTL_BIN, "online"])
    if result.returncode != 0:
        log.warning("agentctl online 失败: %s", result.stderr.strip())
        return False
    return ORCHESTRATOR_ID in result.stdout


def send_ipc(message: str) -> bool:
    """
    通过 ipcsend CLI 向 orchestrator 发送 IPC 消息。
    消息到达时 brain_ipc_c 会在 orchestrator 的 tmux pane 注入 [IPC] 通知，
    唤醒 Claude session 调用 ipc_recv()。
    """
    result = _run(["ipcsend", ORCHESTRATOR_ID, message])
    if result.returncode != 0:
        log.warning("IPC 发送失败 → %s: %s", ORCHESTRATOR_ID, result.stderr.strip())
        return False
    return True


def agentctl_start() -> bool:
    """通过 agentctl 启动 orchestrator session"""
    result = _run([AGENTCTL_BIN, "start", "--apply", ORCHESTRATOR_ID])
    if result.returncode != 0:
        log.error("agentctl start 失败: %s", result.stderr.strip())
        return False
    log.info("agentctl start 成功: %s", ORCHESTRATOR_ID)
    return True


def agentctl_restart() -> bool:
    """通过 agentctl 重启 orchestrator session"""
    result = _run([AGENTCTL_BIN, "restart", "--apply", ORCHESTRATOR_ID])
    if result.returncode != 0:
        log.error("agentctl restart 失败: %s", result.stderr.strip())
        return False
    log.info("agentctl restart 成功: %s", ORCHESTRATOR_ID)
    return True


# ─── 阶段：等待上线 ───────────────────────────────────────────────────────────

def wait_for_online(timeout: int = ONLINE_TIMEOUT) -> bool:
    """
    等待 orchestrator 出现在 agentctl online 列表。
    若超时仍未上线，返回 False。
    """
    deadline = time.time() + timeout
    poll_interval = 5
    log.info("等待 orchestrator 上线（超时 %ds）: %s", timeout, ORCHESTRATOR_ID)
    while time.time() < deadline:
        if is_online():
            log.info("orchestrator 已上线")
            return True
        time.sleep(poll_interval)
    log.error("等待 orchestrator 上线超时（%ds）", timeout)
    return False


# ─── 阶段：发送初始化事件 ──────────────────────────────────────────────────────

def send_init_event() -> None:
    """
    向 orchestrator 发送 ORCHESTRATOR_INIT 消息。
    orchestrator Claude session 收到后执行启动自检：
      - 验证 IPC/task_manager 连通
      - 加载 project_plan、roster
      - 发送心跳给 brain infra
      - 进入第一个项目阶段
    """
    payload = json.dumps({
        "event": "ORCHESTRATOR_INIT",
        "project_id": PROJECT_ID,
        "sandbox_id": SANDBOX_ID,
        "orchestrator_id": ORCHESTRATOR_ID,
    }, ensure_ascii=False)
    msg = f"[DRIVER] {payload}"
    if send_ipc(msg):
        log.info("ORCHESTRATOR_INIT 已发送")
    else:
        log.warning("ORCHESTRATOR_INIT 发送失败，orchestrator 可能需要手动触发")


# ─── 阶段：发送心跳 ───────────────────────────────────────────────────────────

def send_heartbeat() -> None:
    """
    定期唤醒 orchestrator，让其检查：
      - 是否有 stale ACTIVE tasks（worker 失联）
      - 是否有 READY tasks 尚未 dispatch
      - 是否满足 EXECUTION_READY_FOR_RELEASE 条件
    """
    payload = json.dumps({
        "event": "HEARTBEAT",
        "project_id": PROJECT_ID,
    }, ensure_ascii=False)
    msg = f"[DRIVER] {payload}"
    if send_ipc(msg):
        log.debug("HEARTBEAT 已发送")
    else:
        log.warning("HEARTBEAT 发送失败")


# ─── 阶段：恢复处理 ───────────────────────────────────────────────────────────

def handle_offline(consecutive_failures: int) -> bool:
    """
    orchestrator 离线时的处理流程：
    1. 尝试 agentctl restart
    2. 等待重新上线
    3. 上线后发送 RECOVERING 事件（orchestrator 重载 task_manager snapshot）

    返回 True 表示恢复成功，False 表示需要升级处理。
    """
    log.warning("orchestrator 离线（连续 %d 次），尝试重启", consecutive_failures)

    if not agentctl_restart():
        return False

    if not wait_for_online(timeout=ONLINE_TIMEOUT):
        return False

    # 发送 RECOVERING 事件，orchestrator 将重新从 task_manager 加载 snapshot
    payload = json.dumps({
        "event": "RECOVERING",
        "project_id": PROJECT_ID,
        "sandbox_id": SANDBOX_ID,
        "orchestrator_id": ORCHESTRATOR_ID,
        "consecutive_failures": consecutive_failures,
    }, ensure_ascii=False)
    msg = f"[DRIVER] {payload}"
    if send_ipc(msg):
        log.info("RECOVERING 事件已发送，orchestrator 将重载 task snapshot")
    return True


# ─── 主循环 ───────────────────────────────────────────────────────────────────

def main() -> None:
    # 参数校验
    if not ORCHESTRATOR_ID:
        log.critical("ORCHESTRATOR_ID 未设置，退出")
        sys.exit(1)
    if not PROJECT_ID:
        log.critical("PROJECT_ID 未设置，退出")
        sys.exit(1)

    log.info("orchestrator_driver 启动 | project=%s sandbox=%s orchestrator=%s",
             PROJECT_ID, SANDBOX_ID, ORCHESTRATOR_ID)

    # ── 步骤1：确保 orchestrator 进程已启动 ──
    if not is_online():
        log.info("orchestrator 尚未上线，执行 agentctl start")
        agentctl_start()

    if not wait_for_online():
        log.critical("orchestrator 无法上线，driver 退出（supervisor 将重启本进程）")
        sys.exit(1)

    # ── 步骤2：发送初始化事件 ──
    send_init_event()

    # ── 步骤3：主心跳循环 ──
    consecutive_failures = 0
    last_heartbeat = time.time()

    log.info("进入心跳循环，间隔 %ds", HEARTBEAT_INTERVAL)

    while True:
        time.sleep(HEARTBEAT_INTERVAL)

        if is_online():
            consecutive_failures = 0
            send_heartbeat()
            last_heartbeat = time.time()
        else:
            consecutive_failures += 1
            log.warning("orchestrator 不在线（第 %d 次）", consecutive_failures)

            if consecutive_failures >= MAX_RESTART_ATTEMPTS:
                log.error(
                    "orchestrator 连续 %d 次离线，超过阈值 %d，driver 退出升级处理",
                    consecutive_failures, MAX_RESTART_ATTEMPTS,
                )
                # supervisor 会重启 driver，同时通知 PMO（由 orchestrator 在 RECOVERING 中执行）
                sys.exit(2)

            recovered = handle_offline(consecutive_failures)
            if recovered:
                consecutive_failures = 0
                last_heartbeat = time.time()
            else:
                log.error("恢复失败（第 %d 次），等待下次重试", consecutive_failures)


if __name__ == "__main__":
    main()
