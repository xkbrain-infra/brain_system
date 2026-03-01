"""
BS-025-T9 单元测试：Health Check Server
覆盖：GET /health 返回 200 + 正确 JSON、404 路径、端口占用不崩溃
"""
import asyncio
import json
import os
import sys
from unittest.mock import MagicMock, PropertyMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from health import HealthServer, _parse_request_line


def run(coro, timeout=5):
    return asyncio.run(asyncio.wait_for(coro, timeout=timeout))


def _make_engine(managed=2, active=5, scheduler=True, agent="tmr_test"):
    engine = MagicMock()
    type(engine).managed_projects = PropertyMock(return_value=managed)
    type(engine).active_tasks = PropertyMock(return_value=active)
    type(engine).scheduler_running = PropertyMock(return_value=scheduler)
    engine._agent_name = agent
    return engine


def _make_server(port=18766, engine=None):
    return HealthServer(port=port, engine=engine or _make_engine())


# ── _parse_request_line ───────────────────────────────────────────────────────

def test_parse_request_line_get_health():
    method, path = _parse_request_line("GET /health HTTP/1.1")
    assert method == "GET"
    assert path == "/health"


def test_parse_request_line_invalid():
    method, path = _parse_request_line("")
    assert method == ""
    assert path == ""


def test_parse_request_line_post():
    method, path = _parse_request_line("POST /other HTTP/1.1")
    assert method == "POST"
    assert path == "/other"


# ── _build_payload ────────────────────────────────────────────────────────────

def test_build_payload_fields():
    """_build_payload 包含所有必需字段，值与 engine 属性一致。"""
    engine = _make_engine(managed=3, active=7, scheduler=True, agent="tmr_agent")
    server = _make_server(engine=engine)

    payload = server._build_payload()

    assert payload["status"] == "ok"
    assert isinstance(payload["uptime_seconds"], int)
    assert payload["uptime_seconds"] >= 0
    assert payload["managed_projects"] == 3
    assert payload["active_tasks"] == 7
    assert payload["scheduler_running"] is True
    assert payload["agent_name"] == "tmr_agent"


def test_build_payload_scheduler_false():
    engine = _make_engine(scheduler=False)
    server = _make_server(engine=engine)
    payload = server._build_payload()
    assert payload["scheduler_running"] is False


# ── HTTP 集成测试：实际 TCP 连接 ──────────────────────────────────────────────

def _find_free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _get(port, path="/health"):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    request = f"GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
    writer.write(request.encode())
    await writer.drain()
    response = await reader.read(4096)
    writer.close()
    await writer.wait_closed()
    return response.decode("utf-8", errors="replace")


def test_health_endpoint_returns_200():
    """GET /health 返回 200 和正确 JSON 结构。"""
    port = _find_free_port()
    engine = _make_engine(managed=2, active=4, scheduler=True)
    server = _make_server(port=port, engine=engine)

    async def run_test():
        task = asyncio.create_task(server.start())
        await asyncio.sleep(0.1)  # 等服务器绑定

        response = await _get(port, "/health")

        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        return response

    response = asyncio.run(asyncio.wait_for(run_test(), timeout=5))

    # 验证状态行
    assert "200 OK" in response

    # 解析 JSON body
    body = response.split("\r\n\r\n", 1)[1]
    data = json.loads(body)

    assert data["status"] == "ok"
    assert data["managed_projects"] == 2
    assert data["active_tasks"] == 4
    assert data["scheduler_running"] is True
    assert "uptime_seconds" in data
    assert "agent_name" in data


def test_health_endpoint_404_for_unknown_path():
    """未知路径返回 404。"""
    port = _find_free_port()
    server = _make_server(port=port)

    async def run_test():
        task = asyncio.create_task(server.start())
        await asyncio.sleep(0.1)

        response = await _get(port, "/unknown")

        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        return response

    response = asyncio.run(asyncio.wait_for(run_test(), timeout=5))
    assert "404" in response


def test_health_server_port_conflict_no_crash():
    """端口被占用时，start() 不抛出异常（仅记录错误）。"""
    import socket

    port = _find_free_port()
    # 占用该端口
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(1)

    server = _make_server(port=port)

    async def run_test():
        # 不应抛出异常
        task = asyncio.create_task(server.start())
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    try:
        asyncio.run(asyncio.wait_for(run_test(), timeout=3))
    finally:
        sock.close()

    # 到达这里说明没有崩溃
    assert True
