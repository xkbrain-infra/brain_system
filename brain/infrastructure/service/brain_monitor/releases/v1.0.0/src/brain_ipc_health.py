#!/usr/bin/env python3
"""
Brain-IPC 健康检查模块
监控 brain-ipc daemon 的运行状态、队列状态和 agent 注册情况
"""

import json
import os
import socket
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# 配置常量
DAEMON_BIN = "/brain/bin/brain_ipc"
SOCKET_PATH = "/tmp/brain_ipc.sock"
LOG_FILE = "/brain/runtime/logs/brain_ipc.log"
PID_FILE = "/tmp/brain_ipc.pid"

# 告警阈值
ALERT_QUEUE_BACKLOG = 100
ALERT_INFLIGHT_TIMEOUT = 10
ALERT_AGENT_OFFLINE = 5


@dataclass
class HealthCheckResult:
    """健康检查结果"""
    healthy: bool
    status: str  # "healthy", "degraded", "down"
    checks: dict[str, Any]
    alerts: list[str]


def check_daemon_process() -> dict[str, Any]:
    """检查 daemon 进程是否存在（PID 文件检查）"""
    result = {
        "exists": False,
        "pid": None,
        "running": False
    }

    if not os.path.exists(PID_FILE):
        result["error"] = "PID file not found"
        return result

    try:
        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())
            result["pid"] = pid

        # 检查进程是否存在
        try:
            os.kill(pid, 0)  # 信号 0 不杀死进程，只检查是否存在
            result["exists"] = True
            result["running"] = True
        except OSError:
            result["error"] = f"Process {pid} not running"
            result["running"] = False

    except (ValueError, IOError) as e:
        result["error"] = f"Failed to read PID: {e}"

    return result


def check_socket() -> dict[str, Any]:
    """检查 socket 是否存在且可连接"""
    result = {
        "exists": False,
        "connectable": False
    }

    if not os.path.exists(SOCKET_PATH):
        result["error"] = "Socket file not found"
        return result

    result["exists"] = True
    result["path"] = SOCKET_PATH

    # 尝试连接
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(SOCKET_PATH)
        sock.close()
        result["connectable"] = True
    except Exception as e:
        result["error"] = f"Cannot connect: {e}"

    return result


def check_log_errors() -> dict[str, Any]:
    """检查日志文件是否有错误"""
    result = {
        "has_errors": False,
        "error_count": 0,
        "last_error": None
    }

    if not os.path.exists(LOG_FILE):
        result["error"] = "Log file not found"
        return result

    try:
        # 读取最后 1000 行检查错误
        with open(LOG_FILE, 'r') as f:
            lines = f.readlines()[-1000:]

        errors = [line for line in lines if 'ERROR' in line or 'FATAL' in line]
        result["error_count"] = len(errors)
        result["has_errors"] = len(errors) > 0

        if errors:
            result["last_error"] = errors[-1].strip()[:200]

    except IOError as e:
        result["error"] = f"Failed to read log: {e}"

    return result


def send_ipc_command(action: str, data: dict | None = None, timeout: float = 5.0) -> dict:
    """发送命令到 brain daemon 获取状态"""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(SOCKET_PATH)

        request = {"action": action, "data": data or {}}
        request_json = json.dumps(request, ensure_ascii=False) + "\n"

        sock.sendall(request_json.encode("utf-8"))

        response_bytes = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response_bytes += chunk
            if b"\n" in response_bytes:
                break

        sock.close()

        if not response_bytes:
            return {"status": "error", "error": "Empty response"}

        return json.loads(response_bytes.decode("utf-8"))

    except FileNotFoundError:
        return {"status": "error", "error": f"Socket not found: {SOCKET_PATH}"}
    except ConnectionRefusedError:
        return {"status": "error", "error": "Connection refused"}
    except socket.timeout:
        return {"status": "error", "error": "Request timeout"}
    except json.JSONDecodeError as e:
        return {"status": "error", "error": f"Invalid JSON: {e}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def check_queue_status() -> dict[str, Any]:
    """检查队列状态"""
    result = send_ipc_command("ipc_status", {})

    if result.get("status") != "ok":
        return {
            "available": False,
            "error": result.get("error", "Failed to get status")
        }

    stats = result.get("stats", {})
    msgqueue = stats.get("msgqueue", {})

    return {
        "available": True,
        "total": msgqueue.get("total", 0),
        "pending": msgqueue.get("pending", 0),
        "inflight": msgqueue.get("inflight", 0),
        "delayed": stats.get("delayed_queue", {}).get("count", 0),
    }


def check_agent_registration() -> dict[str, Any]:
    """检查 agent 注册情况"""
    result = send_ipc_command("agent_list", {"include_offline": False})

    if result.get("status") != "ok":
        return {
            "available": False,
            "error": result.get("error", "Failed to list agents")
        }

    agents = result.get("agents", [])

    # 检查每个 agent 的心跳超时情况
    now = time.time()
    stale_agents = []
    for agent in agents:
        last_seen = agent.get("last_seen", 0)
        if now - last_seen > 300:  # 5 分钟超时
            stale_agents.append(agent.get("name", "unknown"))

    return {
        "available": True,
        "online_count": len(agents),
        "stale_count": len(stale_agents),
        "stale_agents": stale_agents,
    }


def check_daemon_status() -> dict[str, Any]:
    """检查 daemon 基本状态（ping）"""
    result = send_ipc_command("ping", {})

    return {
        "responding": result.get("status") in ("ok", "pong"),
        "raw_status": result.get("status")
    }


def perform_health_check() -> HealthCheckResult:
    """执行完整的健康检查"""
    checks = {}
    alerts = []

    # 1. 基础指标监控
    checks["daemon_process"] = check_daemon_process()
    checks["socket"] = check_socket()
    checks["log_errors"] = check_log_errors()

    # 2. 队列状态监控
    checks["queue_status"] = check_queue_status()

    # 3. Agent 注册监控
    checks["agent_registration"] = check_agent_registration()

    # 4. Daemon ping
    checks["daemon_ping"] = check_daemon_status()

    # 汇总判断
    is_healthy = True

    # 检查 daemon 进程
    if not checks["daemon_process"].get("running"):
        alerts.append(f"Daemon process not running (PID: {checks['daemon_process'].get('pid')})")
        is_healthy = False

    # 检查 socket
    if not checks["socket"].get("connectable"):
        alerts.append("Socket not connectable")
        is_healthy = False

    # 检查队列积压
    if checks["queue_status"].get("available"):
        pending = checks["queue_status"].get("pending", 0)
        if pending > ALERT_QUEUE_BACKLOG:
            alerts.append(f"Queue backlog ({pending}) exceeds threshold ({ALERT_QUEUE_BACKLOG})")
            is_healthy = False

        inflight = checks["queue_status"].get("inflight", 0)
        if inflight > ALERT_INFLIGHT_TIMEOUT:
            alerts.append(f"Inflight messages ({inflight}) exceeds threshold ({ALERT_INFLIGHT_TIMEOUT})")

    # 检查 agent 离线
    if checks["agent_registration"].get("available"):
        stale_count = checks["agent_registration"].get("stale_count", 0)
        if stale_count > 0:
            stale_agents = checks["agent_registration"].get("stale_agents", [])
            alerts.append(f"{stale_count} agents stale: {', '.join(stale_agents[:3])}")

    # 检查日志错误
    if checks["log_errors"].get("has_errors"):
        error_count = checks["log_errors"].get("error_count", 0)
        alerts.append(f"Log has {error_count} errors")

    # 确定状态
    if is_healthy and not alerts:
        status = "healthy"
    elif is_healthy and alerts:
        status = "degraded"
    else:
        status = "down"

    return HealthCheckResult(
        healthy=is_healthy,
        status=status,
        checks=checks,
        alerts=alerts
    )


def format_health_report(result: HealthCheckResult) -> str:
    """格式化健康检查报告"""
    output = []
    output.append(f"\n{'='*80}")
    output.append(f"Brain-IPC Health Check Report")
    output.append(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    output.append(f"{'='*80}\n")

    # 总体状态
    status_icon = "✅" if result.healthy else ("⚠️" if result.status == "degraded" else "❌")
    output.append(f"Overall Status: {status_icon} {result.status.upper()}\n")

    # 详细检查结果
    output.append("--- Daemon Process ---")
    proc = result.checks.get("daemon_process", {})
    output.append(f"  Running: {'Yes' if proc.get('running') else 'No'}")
    output.append(f"  PID: {proc.get('pid', 'N/A')}")
    if proc.get("error"):
        output.append(f"  Error: {proc['error']}")

    output.append("\n--- Socket ---")
    sock = result.checks.get("socket", {})
    output.append(f"  Exists: {'Yes' if sock.get('exists') else 'No'}")
    output.append(f"  Connectable: {'Yes' if sock.get('connectable') else 'No'}")
    if sock.get("error"):
        output.append(f"  Error: {sock['error']}")

    output.append("\n--- Queue Status ---")
    queue = result.checks.get("queue_status", {})
    if queue.get("available"):
        output.append(f"  Pending: {queue.get('pending', 0)}")
        output.append(f"  Inflight: {queue.get('inflight', 0)}")
        output.append(f"  Delayed: {queue.get('delayed', 0)}")
    else:
        output.append(f"  Error: {queue.get('error', 'Unknown')}")

    output.append("\n--- Agent Registration ---")
    agents = result.checks.get("agent_registration", {})
    if agents.get("available"):
        output.append(f"  Online: {agents.get('online_count', 0)}")
        output.append(f"  Stale: {agents.get('stale_count', 0)}")
        if agents.get("stale_agents"):
            output.append(f"  Stale Agents: {', '.join(agents['stale_agents'][:5])}")
    else:
        output.append(f"  Error: {agents.get('error', 'Unknown')}")

    output.append("\n--- Log Errors ---")
    log = result.checks.get("log_errors", {})
    output.append(f"  Error Count: {log.get('error_count', 0)}")
    if log.get("last_error"):
        output.append(f"  Last Error: {log['last_error'][:100]}")

    # 告警
    if result.alerts:
        output.append(f"\n--- Alerts ({len(result.alerts)}) ---")
        for alert in result.alerts:
            output.append(f"  ⚠️  {alert}")

    output.append("\n" + "="*80 + "\n")
    return "\n".join(output)


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='Brain-IPC Health Check')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--alert-threshold-queue', type=int, default=ALERT_QUEUE_BACKLOG,
                        help='Queue backlog threshold for alerts')
    parser.add_argument('--alert-threshold-inflight', type=int, default=ALERT_INFLIGHT_TIMEOUT,
                        help='Inflight timeout threshold for alerts')
    parser.add_argument('--alert-threshold-offline', type=int, default=ALERT_AGENT_OFFLINE,
                        help='Offline agent threshold for alerts')

    args = parser.parse_args()

    # 执行健康检查
    result = perform_health_check()

    # 输出
    if args.json:
        print(json.dumps({
            "healthy": result.healthy,
            "status": result.status,
            "checks": result.checks,
            "alerts": result.alerts
        }, indent=2, default=str))
    else:
        print(format_health_report(result))

    # 根据状态返回退出码
    sys.exit(0 if result.healthy else 1)


if __name__ == '__main__':
    main()
