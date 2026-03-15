"""WebSocket Log Stream API - T5 Implementation.

Provides WebSocket endpoint for real-time log streaming from services.
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

# Import log reader from core
import sys
sys.path.insert(0, "/brain/sandbox/brain_dashboard_20260311/src")
from core.log_reader import LogReader, LogLine, LogBuffer

router = APIRouter(prefix="/logs", tags=["logs"])
logger = logging.getLogger("agent_dashboard.logs_api")

# Global log reader instance
_log_reader: Optional[LogReader] = None
_log_buffer = LogBuffer(max_lines=5000)


def get_log_reader() -> LogReader:
    """Get or create global log reader instance."""
    global _log_reader
    if _log_reader is None:
        _log_reader = LogReader()
    return _log_reader


async def _log_callback(log_line: LogLine) -> None:
    """Callback to add log lines to buffer."""
    await _log_buffer.append(log_line)


@router.websocket("/ws/{service}")
async def websocket_log_stream(websocket: WebSocket, service: str):
    """WebSocket endpoint for real-time log streaming.

    Args:
        websocket: WebSocket connection
        service: Service name to stream logs for (or 'all' for all services)

    Query Parameters:
        tail: Number of lines to send initially (default: 100)
        follow: Whether to continue streaming new lines (default: true)

    Messages:
        Client -> Server:
            - {"action": "pause"}: Pause log streaming
            - {"action": "resume"}: Resume log streaming
            - {"action": "ping"}: Keep connection alive

        Server -> Client:
            - {"type": "log", "data": {...}}: Log line
            - {"type": "stats", "data": {...}}: Reader statistics
            - {"type": "error", "message": "..."}: Error message
            - {"type": "ack", "action": "..."}: Action acknowledgment
    """
    await websocket.accept()
    client_id = f"{websocket.client.host}:{websocket.client.port}"
    logger.info(f"WebSocket connection accepted for service '{service}' from {client_id}")

    # Parse query parameters
    query_params = dict(websocket.query_params)
    tail_lines = int(query_params.get("tail", "100"))
    follow = query_params.get("follow", "true").lower() == "true"

    reader = get_log_reader()

    # Start log reader if not running
    if not reader._running:
        reader.register_callback(_log_callback)
        asyncio.create_task(reader.start_watching(service=None))

    # Send initial buffer for the requested service
    try:
        if service == "all":
            initial_lines = await _log_buffer.get_lines(count=tail_lines)
        else:
            initial_lines = await _log_buffer.get_lines(
                count=tail_lines,
                service=service,
            )

        for log_line in initial_lines:
            await websocket.send_json({
                "type": "log",
                "data": {
                    "service": log_line.service,
                    "content": log_line.content,
                    "timestamp": log_line.timestamp.isoformat(),
                    "line_number": log_line.line_number,
                },
            })

        if not follow:
            await websocket.close()
            return

        # Track last sent line to avoid duplicates
        last_sent_count = len(initial_lines)

        # Main streaming loop
        while True:
            try:
                # Check for client messages (non-blocking)
                try:
                    message = await asyncio.wait_for(
                        websocket.receive_json(),
                        timeout=0.1,
                    )
                    await _handle_client_message(websocket, reader, message)
                except asyncio.TimeoutError:
                    pass

                # Send new log lines
                if reader._running and not reader._paused:
                    current_lines = await _log_buffer.get_lines(
                        service=service if service != "all" else None,
                    )

                    if len(current_lines) > last_sent_count:
                        new_lines = current_lines[last_sent_count:]
                        for log_line in new_lines:
                            if websocket.client_state != WebSocketState.CONNECTED:
                                break

                            await websocket.send_json({
                                "type": "log",
                                "data": {
                                    "service": log_line.service,
                                    "content": log_line.content,
                                    "timestamp": log_line.timestamp.isoformat(),
                                    "line_number": log_line.line_number,
                                },
                            })
                        last_sent_count = len(current_lines)

                # Send stats periodically
                if hasattr(websocket, "_last_stats_time"):
                    if asyncio.get_event_loop().time() - websocket._last_stats_time > 30:
                        stats = reader.get_stats()
                        await websocket.send_json({
                            "type": "stats",
                            "data": stats,
                        })
                        websocket._last_stats_time = asyncio.get_event_loop().time()
                else:
                    websocket._last_stats_time = asyncio.get_event_loop().time()

                # Small delay to prevent tight loop
                await asyncio.sleep(0.05)

            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected: {client_id}")
                break
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                try:
                    await websocket.send_json({
                        "type": "error",
                        "message": str(e),
                    })
                except:
                    pass
                break

    except Exception as e:
        logger.error(f"WebSocket error for {client_id}: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e),
            })
        except:
            pass
    finally:
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()
        except:
            pass
        logger.info(f"WebSocket connection closed for {client_id}")


async def _handle_client_message(
    websocket: WebSocket,
    reader: LogReader,
    message: dict,
) -> None:
    """Handle client control messages."""
    action = message.get("action", "")

    if action == "pause":
        reader.pause()
        await websocket.send_json({
            "type": "ack",
            "action": "pause",
            "status": "paused",
        })
        logger.debug("Log streaming paused")

    elif action == "resume":
        reader.resume()
        await websocket.send_json({
            "type": "ack",
            "action": "resume",
            "status": "resumed",
        })
        logger.debug("Log streaming resumed")

    elif action == "ping":
        await websocket.send_json({
            "type": "ack",
            "action": "ping",
            "status": "ok",
        })

    elif action == "stats":
        stats = reader.get_stats()
        await websocket.send_json({
            "type": "stats",
            "data": stats,
        })

    else:
        await websocket.send_json({
            "type": "error",
            "message": f"Unknown action: {action}",
        })


@router.get("/services")
async def list_log_services():
    """Get list of services with log files.

    Returns:
        JSON with list of services and file counts.
    """
    reader = get_log_reader()
    files = reader.list_log_files()

    # Group by service
    services: dict[str, dict] = {}
    for file_info in files:
        svc = file_info.service
        if svc not in services:
            services[svc] = {
                "name": svc,
                "files": 0,
                "total_size_bytes": 0,
                "total_size_mb": 0.0,
            }
        services[svc]["files"] += 1
        services[svc]["total_size_bytes"] += file_info.size

    # Calculate MB sizes
    for svc in services:
        services[svc]["total_size_mb"] = round(
            services[svc]["total_size_bytes"] / (1024 * 1024), 2
        )

    return {
        "services": list(services.values()),
        "count": len(services),
        "timestamp": asyncio.get_event_loop().time(),
    }


@router.get("/services/{service}/files")
async def list_service_log_files(service: str):
    """Get log files for a specific service.

    Args:
        service: Service name.

    Returns:
        JSON with list of log files.
    """
    reader = get_log_reader()
    all_files = reader.list_log_files()

    # Filter by service
    service_files = [
        {
            "path": str(f.path),
            "service": f.service,
            "size_bytes": f.size,
            "size_mb": round(f.size / (1024 * 1024), 2),
            "modified": f.mtime,
            "is_large": f.is_large,
        }
        for f in all_files
        if f.service == service
    ]

    return {
        "service": service,
        "files": service_files,
        "count": len(service_files),
        "timestamp": asyncio.get_event_loop().time(),
    }
