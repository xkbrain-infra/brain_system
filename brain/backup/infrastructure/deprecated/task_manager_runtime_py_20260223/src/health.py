"""
BS-025-MOD-health: Health Check Server
内置 asyncio HTTP 服务，GET /health 返回运行状态 JSON。
端口由 TMR_HEALTH_PORT 环境变量控制（默认 8766）。
health server 是非核心路径：端口被占用时仅记录错误，主进程继续运行。
"""
import asyncio
import json
import logging
import time
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict

logger = logging.getLogger(__name__)

_START_TIME = time.monotonic()


def _uptime_seconds() -> int:
    return int(time.monotonic() - _START_TIME)


class HealthServer:
    """
    asyncio 原生 HTTP 服务（无 aiohttp 依赖）。
    通过 asyncio.start_server 实现，在独立 task 中运行。
    Engine 在 _init_health_server 中实例化并 create_task(start())。
    """

    def __init__(self, port: int, engine):
        self._port = port
        self._engine = engine
        self._server: Any = None

    async def start(self) -> None:
        """启动 HTTP 服务，端口被占用时仅记录错误不抛出。"""
        try:
            self._server = await asyncio.start_server(
                self._handle_connection,
                host="0.0.0.0",
                port=self._port,
            )
            logger.info(f"HealthServer listening on port {self._port}")
            async with self._server:
                await self._server.serve_forever()
        except OSError as e:
            logger.error(
                f"HealthServer failed to bind port {self._port}: {e}, "
                f"health check will be unavailable"
            )

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """处理单个 HTTP 连接，仅支持 GET /health。"""
        try:
            raw = await asyncio.wait_for(reader.read(1024), timeout=5.0)
            request_line = raw.decode("utf-8", errors="replace").split("\r\n")[0]
            method, path = _parse_request_line(request_line)

            if method == "GET" and path in ("/health", "/health/"):
                body = json.dumps(self._build_payload(), ensure_ascii=False)
                response = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(body.encode())}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                    f"{body}"
                )
            else:
                response = (
                    "HTTP/1.1 404 Not Found\r\n"
                    "Content-Length: 0\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )

            writer.write(response.encode("utf-8"))
            await writer.drain()
        except asyncio.TimeoutError:
            logger.debug("Health connection read timeout")
        except Exception as e:
            logger.debug(f"Health connection error: {e}")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    def _build_payload(self) -> Dict[str, Any]:
        """从 Engine 读取运行时指标，构建响应 JSON。"""
        return {
            "status": "ok",
            "uptime_seconds": _uptime_seconds(),
            "managed_projects": self._engine.managed_projects,
            "active_tasks": self._engine.active_tasks,
            "scheduler_running": self._engine.scheduler_running,
            "agent_name": getattr(self._engine, "_agent_name", "task_manager_runtime"),
        }


def _parse_request_line(line: str):
    """解析 HTTP 请求行，返回 (method, path)，失败返回 ('', '')。"""
    parts = line.strip().split(" ")
    if len(parts) >= 2:
        return parts[0].upper(), parts[1]
    return "", ""
