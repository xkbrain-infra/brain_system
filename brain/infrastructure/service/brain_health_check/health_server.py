#!/usr/bin/env python3
"""
health_server.py — Brain System Health Check HTTP Service
BS-024 / Spec: 05_solution.yaml

Modules implemented:
  M1: HealthRequestHandler
  M2: HealthChecker
  M3: IpcDaemonProbe (check_ipc_daemon)
  M4: ServiceHeartbeatProbe (check_services)
  M5: ServerMain
"""

import json
import os
import signal
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event

# ──────────────────────────────────────────────
# 环境变量配置
# ──────────────────────────────────────────────
HEALTH_CHECK_PORT = int(os.environ.get("HEALTH_CHECK_PORT", "8765"))
BRAIN_IPC_SOCKET = os.environ.get("BRAIN_IPC_SOCKET", "/tmp/brain_ipc.sock")
HEALTH_CHECK_TIMEOUT = float(os.environ.get("HEALTH_CHECK_TIMEOUT", "2.0"))
HEALTH_CHECK_PROBE_TIMEOUT = float(os.environ.get("HEALTH_CHECK_PROBE_TIMEOUT", "0.5"))
HEALTH_CHECK_VERSION = os.environ.get("HEALTH_CHECK_VERSION", "1.0.0")

# 监控目标服务
TARGET_SERVICES = ["service-agentctl", "service-timer", "service-brain_gateway"]

# 心跳超时阈值（秒）
HEARTBEAT_TIMEOUT_S = 60


# ──────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────
@dataclass
class ProbeResult:
    status: str      # "up" | "down" | "unknown"
    latency_ms: float
    message: str


@dataclass
class HealthResult:
    overall_status: str   # "healthy" | "degraded" | "down" | "unknown"
    timestamp: str
    version: str
    services: dict        # name → ProbeResult
    latency_ms: float


# ──────────────────────────────────────────────
# M3: IpcDaemonProbe
# ──────────────────────────────────────────────
def check_ipc_daemon(socket_path: str = BRAIN_IPC_SOCKET,
                     timeout: float = HEALTH_CHECK_PROBE_TIMEOUT) -> ProbeResult:
    """通过 UNIX socket connect + ping 测试 IPC daemon 存活性。"""
    start = time.monotonic()
    sock = None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(socket_path)

        request = json.dumps({"action": "ping", "data": {}}) + "\n"
        sock.sendall(request.encode())

        response = b""
        while not response.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk

        latency = (time.monotonic() - start) * 1000

        if not response:
            return ProbeResult("down", latency, "ping failed: no response")

        result = json.loads(response.decode())
        if result.get("status") == "ok":
            uptime = result.get("uptime", "?")
            return ProbeResult("up", latency, f"uptime={uptime}s")
        else:
            return ProbeResult("down", latency, f"ping error: {result}")

    except FileNotFoundError:
        latency = (time.monotonic() - start) * 1000
        return ProbeResult("down", latency, f"socket not found: {socket_path}")
    except socket.timeout:
        latency = (time.monotonic() - start) * 1000
        return ProbeResult("down", latency, "connection timeout")
    except Exception as e:
        latency = (time.monotonic() - start) * 1000
        return ProbeResult("down", latency, str(e))
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass


# ──────────────────────────────────────────────
# M4: ServiceHeartbeatProbe
# ──────────────────────────────────────────────
def check_services(socket_path: str = BRAIN_IPC_SOCKET,
                   target_services: list = None,
                   timeout: float = HEALTH_CHECK_PROBE_TIMEOUT) -> dict:
    """通过 IPC daemon agent_list API 批量查询服务心跳状态。"""
    if target_services is None:
        target_services = TARGET_SERVICES

    start = time.monotonic()
    now = time.time()
    sock = None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(socket_path)

        request = json.dumps({
            "action": "agent_list",
            "data": {"include_offline": True}
        }) + "\n"
        sock.sendall(request.encode())

        response = b""
        while not response.endswith(b"\n"):
            chunk = sock.recv(65536)
            if not chunk:
                break
            response += chunk

        latency = (time.monotonic() - start) * 1000
        data = json.loads(response.decode())

        # 构建 service_name → instance 映射
        instances = data.get("instances", [])
        service_map = {}
        for inst in instances:
            name = inst.get("agent_name") or inst.get("service_name", "")
            if name in target_services:
                service_map[name] = inst

        results = {}
        for svc in target_services:
            if svc not in service_map:
                results[svc] = ProbeResult("down", latency, "not registered")
            else:
                inst = service_map[svc]
                last_hb = inst.get("last_heartbeat", 0)
                idle_seconds = now - last_hb if last_hb > 0 else float("inf")
                is_online = inst.get("online", False)

                if is_online and idle_seconds < HEARTBEAT_TIMEOUT_S:
                    results[svc] = ProbeResult("up", latency,
                                               f"idle={idle_seconds:.0f}s")
                else:
                    results[svc] = ProbeResult("down", latency,
                                               f"offline, idle={idle_seconds:.0f}s, last_seen={last_hb}")
        return results

    except Exception as e:
        latency = (time.monotonic() - start) * 1000
        return {svc: ProbeResult("unknown", latency, str(e))
                for svc in target_services}
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass


# ──────────────────────────────────────────────
# M2: HealthChecker
# ──────────────────────────────────────────────
class HealthChecker:
    """编排所有服务的健康探测，并行执行，聚合结果。"""

    def __init__(self,
                 socket_path: str = BRAIN_IPC_SOCKET,
                 target_services: list = None,
                 probe_timeout: float = HEALTH_CHECK_PROBE_TIMEOUT,
                 total_timeout: float = HEALTH_CHECK_TIMEOUT,
                 version: str = HEALTH_CHECK_VERSION):
        self.socket_path = socket_path
        self.target_services = target_services or TARGET_SERVICES
        self.probe_timeout = probe_timeout
        self.total_timeout = total_timeout
        self.version = version

    def run_all_checks(self) -> HealthResult:
        """并行执行所有探测，返回聚合后的健康结果。"""
        start = time.monotonic()
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

        services = {}
        ipc_result = None
        service_results = {}

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                ipc_future = executor.submit(
                    check_ipc_daemon, self.socket_path, self.probe_timeout
                )
                svc_future = executor.submit(
                    check_services, self.socket_path, self.target_services, self.probe_timeout
                )

                remaining = self.total_timeout
                deadline = start + self.total_timeout

                # 等待 IPC daemon 探测结果
                try:
                    remaining = max(0.0, deadline - time.monotonic())
                    ipc_result = ipc_future.result(timeout=remaining)
                except (FuturesTimeoutError, Exception) as e:
                    ipc_result = ProbeResult("unknown", self.probe_timeout * 1000, str(e))

                # 等待服务心跳探测结果
                try:
                    remaining = max(0.0, deadline - time.monotonic())
                    service_results = svc_future.result(timeout=remaining)
                except (FuturesTimeoutError, Exception) as e:
                    service_results = {
                        svc: ProbeResult("unknown", 0, str(e))
                        for svc in self.target_services
                    }

        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            return HealthResult(
                overall_status="unknown",
                timestamp=timestamp,
                version=self.version,
                services={
                    "brain_ipc_daemon": ProbeResult("unknown", 0, str(e)),
                    **{svc: ProbeResult("unknown", 0, "check failed") for svc in self.target_services}
                },
                latency_ms=latency,
            )

        # 如果 IPC daemon 不可达，所有服务标记为 unknown（跳过查询结果）
        if ipc_result.status != "up":
            service_results = {
                svc: ProbeResult("unknown", 0, "skipped: ipc daemon unavailable")
                for svc in self.target_services
            }

        services["brain_ipc_daemon"] = ipc_result
        services.update(service_results)

        overall_status = self._compute_overall(ipc_result, service_results)
        latency = (time.monotonic() - start) * 1000

        return HealthResult(
            overall_status=overall_status,
            timestamp=timestamp,
            version=self.version,
            services=services,
            latency_ms=latency,
        )

    @staticmethod
    def _compute_overall(ipc_result: ProbeResult, service_results: dict) -> str:
        """
        ADR-003 overall_status 计算规则：
        - IPC daemon down → "down"
        - IPC daemon up + 全部服务 up → "healthy"
        - IPC daemon up + 任一服务 down → "degraded"
        - 无法执行任何检查 → "unknown"
        """
        if ipc_result.status == "unknown":
            return "unknown"
        if ipc_result.status == "down":
            return "down"

        # ipc_result.status == "up"
        if not service_results:
            return "healthy"

        statuses = [r.status for r in service_results.values()]
        if all(s == "up" for s in statuses):
            return "healthy"
        if any(s == "down" for s in statuses):
            return "degraded"
        # 有 unknown，但没有 down
        return "degraded"


# HTTP 状态码映射
OVERALL_TO_HTTP = {
    "healthy": 200,
    "degraded": 503,
    "down": 503,
    "unknown": 503,
}


# ──────────────────────────────────────────────
# M1: HealthRequestHandler
# ──────────────────────────────────────────────
class HealthRequestHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器，路由并返回健康检查结果。"""

    checker: HealthChecker = None  # 由 ServerMain 注入

    def do_GET(self):
        req_start = time.monotonic()
        if self.path == "/health":
            self._handle_health(req_start)
        else:
            self._send_error(404, "not found", req_start)

    def do_POST(self):
        self._send_error(405, "method not allowed", time.monotonic())

    def do_PUT(self):
        self._send_error(405, "method not allowed", time.monotonic())

    def do_DELETE(self):
        self._send_error(405, "method not allowed", time.monotonic())

    def do_PATCH(self):
        self._send_error(405, "method not allowed", time.monotonic())

    def _handle_health(self, req_start: float):
        try:
            result = self.checker.run_all_checks()
            http_status = OVERALL_TO_HTTP.get(result.overall_status, 503)
            body = {
                "status": result.overall_status,
                "timestamp": result.timestamp,
                "version": result.version,
                "latency_ms": round(result.latency_ms, 2),
                "services": {
                    name: {
                        "status": probe.status,
                        "latency_ms": round(probe.latency_ms, 2),
                        "message": probe.message,
                    }
                    for name, probe in result.services.items()
                },
            }
            self._send_json(http_status, body, req_start)
        except Exception as e:
            self._send_error(500, "internal error", req_start)

    def _send_error(self, code: int, message: str, req_start: float):
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        body = {"status": "error", "message": message, "timestamp": timestamp}
        self._send_json(code, body, req_start)

    def _send_json(self, status_code: int, body: dict, req_start: float):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        latency_ms = (time.monotonic() - req_start) * 1000
        self.log_access(status_code, latency_ms)

    def log_access(self, status_code: int, latency_ms: float):
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        print(f'[access] {ts} "{self.command} {self.path}" {status_code} {latency_ms:.1f}ms',
              flush=True)

    # 覆盖默认的 log_message 避免重复输出
    def log_message(self, fmt, *args):
        pass


# ──────────────────────────────────────────────
# M5: ServerMain
# ──────────────────────────────────────────────
def main():
    port = HEALTH_CHECK_PORT
    socket_path = BRAIN_IPC_SOCKET

    print(f"[health_server] Starting on port {port}, ipc_socket={socket_path}, "
          f"version={HEALTH_CHECK_VERSION}", flush=True)

    checker = HealthChecker(
        socket_path=socket_path,
        target_services=TARGET_SERVICES,
        probe_timeout=HEALTH_CHECK_PROBE_TIMEOUT,
        total_timeout=HEALTH_CHECK_TIMEOUT,
        version=HEALTH_CHECK_VERSION,
    )

    # 注入 checker 到 handler 类（class-level，避免每次 request 构造）
    HealthRequestHandler.checker = checker

    try:
        server = ThreadingHTTPServer(("", port), HealthRequestHandler)
    except OSError as e:
        print(f"[health_server] Failed to bind port {port}: {e}", file=sys.stderr, flush=True)
        sys.exit(1)

    shutdown_event = Event()

    def handle_sigterm(signum, frame):
        print("[health_server] SIGTERM received, shutting down...", flush=True)
        shutdown_event.set()
        server.shutdown()

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    print(f"[health_server] Listening on 0.0.0.0:{port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        print("[health_server] Shutdown complete.", flush=True)


if __name__ == "__main__":
    main()
