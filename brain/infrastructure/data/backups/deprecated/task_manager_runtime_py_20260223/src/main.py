"""
BS-025 task_manager_runtime 入口
启动 asyncio event loop，运行 Engine。
"""
import asyncio
import logging
import os
import sys


def _setup_logging() -> None:
    level = os.environ.get("TMR_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


async def _amain() -> None:
    from engine import Engine

    # 注入实际 MCP IPC 函数（运行时从 MCP 工具获取）
    try:
        from mcp_ipc import ipc_send, ipc_recv  # noqa: F401 - runtime injection
        engine = Engine()
        engine.inject_ipc(ipc_send, ipc_recv)
    except ImportError:
        # 允许在没有 MCP shim 的情况下启动（用于测试/standalone 模式）
        engine = Engine()

    await engine.run()


def main() -> None:
    _setup_logging()
    logger = logging.getLogger(__name__)
    logger.info(
        f"task_manager_runtime starting "
        f"(agent={os.environ.get('BRAIN_AGENT_NAME', 'task_manager_runtime')})"
    )
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except SystemExit as e:
        sys.exit(e.code)
    except Exception as e:
        logger.critical(f"Unhandled exception in main loop: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
