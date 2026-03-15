import asyncio

import pytest


@pytest.fixture(autouse=True)
def _fresh_event_loop():
    """
    统一每个测试用例的 event loop，避免 asyncio.run/get_event_loop 混用导致的顺序依赖。
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        yield
    finally:
        loop.close()
        asyncio.set_event_loop(None)
