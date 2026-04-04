#!/usr/bin/env python3
"""Compatibility wrapper for legacy sandbox IPC bridge path."""

from __future__ import annotations

import runpy
from pathlib import Path


TARGET = Path(
    "/xkagent_infra/groups/brain/projects/infrastructure/brain_sandbox_service/src/current/ipc_socket_bridge.py"
)


if __name__ == "__main__":
    runpy.run_path(str(TARGET), run_name="__main__")
