"""Log File Reader - T4 Implementation.

Provides safe log file reading with tail -f support and large file optimization.
"""

import os
import time
import glob
import asyncio
import logging
from pathlib import Path
from typing import Callable, Iterator, Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger("agent_dashboard.log_reader")

# Constants for large file optimization
LARGE_FILE_THRESHOLD = 100 * 1024 * 1024  # 100MB
CHUNK_SIZE = 8192  # 8KB read chunks
DEFAULT_TAIL_LINES = 100
LOGS_DIR = Path("/brain/infrastructure/logs")


@dataclass
class LogLine:
    """Represents a single log line with metadata."""
    content: str
    timestamp: datetime
    service: str
    line_number: int


@dataclass
class LogFileInfo:
    """Metadata about a log file."""
    path: Path
    service: str
    size: int
    mtime: float
    is_large: bool


class LogReader:
    """Safe log file reader with tail -f support and large file optimization.

    Features:
        - Tail -f mode for real-time log streaming
        - Large file optimization (>100MB)
        - Pause/resume functionality
        - Memory-efficient chunked reading
        - Automatic log rotation handling
    """

    def __init__(self, logs_dir: Path | str = LOGS_DIR) -> None:
        """Initialize log reader.

        Args:
            logs_dir: Directory containing log files.
        """
        self.logs_dir = Path(logs_dir)
        self._running = False
        self._paused = False
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # Not paused initially
        self._watched_files: dict[str, float] = {}  # path -> last size
        self._callbacks: list[Callable[[LogLine], None]] = []

    def list_log_files(self, pattern: str = "*.log") -> list[LogFileInfo]:
        """List all log files matching pattern.

        Args:
            pattern: Glob pattern for log files.

        Returns:
            List of LogFileInfo objects sorted by mtime (newest first).
        """
        files = []
        try:
            for log_path in self.logs_dir.glob(pattern):
                if not log_path.is_file():
                    continue

                stat = log_path.stat()
                files.append(LogFileInfo(
                    path=log_path,
                    service=self._extract_service_name(log_path),
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    is_large=stat.st_size > LARGE_FILE_THRESHOLD,
                ))
        except Exception as e:
            logger.error(f"Failed to list log files: {e}")

        return sorted(files, key=lambda f: f.mtime, reverse=True)

    def _extract_service_name(self, path: Path) -> str:
        """Extract service name from log file path."""
        # Check if in service subdirectory
        try:
            relative = path.relative_to(self.logs_dir)
            if len(relative.parts) > 1:
                return relative.parts[0]
        except ValueError:
            pass

        # Extract from filename (e.g., "webhook_gateway.log" -> "webhook_gateway")
        return path.stem

    def read_lines(
        self,
        log_path: Path,
        tail_lines: int = DEFAULT_TAIL_LINES,
        follow: bool = False,
    ) -> Iterator[str]:
        """Read lines from log file with optional tail -f behavior.

        Args:
            log_path: Path to log file.
            tail_lines: Number of lines to read from end (0 for all).
            follow: If True, keep watching for new lines.

        Yields:
            Log lines as strings.
        """
        if not log_path.exists():
            logger.warning(f"Log file not found: {log_path}")
            return

        try:
            file_size = log_path.stat().st_size
            is_large = file_size > LARGE_FILE_THRESHOLD

            if is_large and tail_lines > 0:
                # For large files, only read tail efficiently
                yield from self._read_tail_large_file(log_path, tail_lines)
            else:
                # Normal reading for small files or when reading all
                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    if tail_lines > 0:
                        # Read all and return last N lines
                        lines = f.readlines()
                        for line in lines[-tail_lines:]:
                            yield line.rstrip("\n\r")
                    else:
                        for line in f:
                            yield line.rstrip("\n\r")

            if follow:
                # Continue watching for new content
                yield from self._follow_file(log_path)

        except Exception as e:
            logger.error(f"Error reading log file {log_path}: {e}")

    def _read_tail_large_file(self, path: Path, n: int) -> Iterator[str]:
        """Efficiently read last N lines from a large file.

        Uses binary search to find the start position, then reads forward.
        """
        try:
            with open(path, "rb") as f:
                # Seek to end and read backwards in chunks
                f.seek(0, 2)  # End of file
                file_size = f.tell()

                if file_size == 0:
                    return

                # Estimate bytes needed for N lines (assume avg 200 bytes/line)
                estimated_bytes = min(n * 200, file_size)
                pos = max(0, file_size - estimated_bytes)
                f.seek(pos)

                # Read and decode
                data = f.read().decode("utf-8", errors="replace")
                lines = data.split("\n")

                # Skip first partial line if we didn't start from beginning
                if pos > 0 and lines:
                    lines = lines[1:]

                # Yield last N lines
                for line in lines[-n:]:
                    yield line.rstrip("\r")

        except Exception as e:
            logger.error(f"Error reading tail of large file {path}: {e}")

    def _follow_file(self, path: Path) -> Iterator[str]:
        """Follow file for new content (tail -f behavior).

        Handles log rotation by detecting when file is replaced.
        """
        last_inode = None
        last_size = 0

        while self._running:
            try:
                if not path.exists():
                    # File was deleted/rotated, wait for it to reappear
                    time.sleep(0.5)
                    continue

                stat = path.stat()
                current_inode = stat.st_ino
                current_size = stat.st_size

                # Detect rotation (new inode)
                if last_inode is not None and current_inode != last_inode:
                    logger.info(f"Log rotation detected for {path}")
                    last_size = 0

                last_inode = current_inode

                if current_size > last_size:
                    # New content available
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(last_size)

                        while True:
                            line = f.readline()
                            if not line:
                                break
                            yield line.rstrip("\n\r")
                            last_size = f.tell()

                            # Check pause state
                            if self._paused:
                                break

                last_size = current_size

                if not self._paused:
                    time.sleep(0.1)  # 100ms poll interval
                else:
                    # When paused, wait for resume signal
                    time.sleep(0.5)

            except Exception as e:
                logger.error(f"Error following file {path}: {e}")
                time.sleep(1)

    async def start_watching(
        self,
        service: str | None = None,
        tail_lines: int = DEFAULT_TAIL_LINES,
    ) -> None:
        """Start watching log files for changes.

        Args:
            service: Service name to watch (None for all).
            tail_lines: Number of lines to show initially.
        """
        self._running = True
        pattern = f"{service}/*.log" if service else "*.log"

        logger.info(f"Starting log watcher for pattern: {pattern}")

        # Find initial files
        files = self.list_log_files(pattern)
        if not files:
            logger.warning(f"No log files found matching: {pattern}")
            return

        # Start watching each file
        tasks = []
        for file_info in files:
            task = asyncio.create_task(
                self._watch_file(file_info, tail_lines)
            )
            tasks.append(task)

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _watch_file(self, file_info: LogFileInfo, tail_lines: int) -> None:
        """Watch a single file for changes."""
        path_str = str(file_info.path)
        self._watched_files[path_str] = file_info.size

        service = file_info.service
        line_number = 0

        # Read existing content
        for line in self.read_lines(file_info.path, tail_lines, follow=False):
            line_number += 1
            log_line = LogLine(
                content=line,
                timestamp=datetime.now(),
                service=service,
                line_number=line_number,
            )
            await self._notify(log_line)

        # Follow for new content
        if self._running:
            for line in self.read_lines(file_info.path, tail_lines=0, follow=True):
                # Wait if paused
                await self._pause_event.wait()

                if not self._running:
                    break

                line_number += 1
                log_line = LogLine(
                    content=line,
                    timestamp=datetime.now(),
                    service=service,
                    line_number=line_number,
                )
                await self._notify(log_line)

    async def _notify(self, log_line: LogLine) -> None:
        """Notify all registered callbacks."""
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(log_line)
                else:
                    callback(log_line)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def register_callback(self, callback: Callable[[LogLine], None]) -> None:
        """Register a callback to receive log lines."""
        self._callbacks.append(callback)

    def unregister_callback(self, callback: Callable[[LogLine], None]) -> None:
        """Unregister a callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def pause(self) -> None:
        """Pause log reading."""
        self._paused = True
        self._pause_event.clear()
        logger.info("Log reader paused")

    def resume(self) -> None:
        """Resume log reading."""
        self._paused = False
        self._pause_event.set()
        logger.info("Log reader resumed")

    def stop(self) -> None:
        """Stop log watching."""
        self._running = False
        self.resume()  # Ensure any paused waits wake up
        logger.info("Log reader stopped")

    def is_paused(self) -> bool:
        """Check if reader is paused."""
        return self._paused

    def get_stats(self) -> dict:
        """Get reader statistics."""
        files = self.list_log_files()
        total_size = sum(f.size for f in files)
        large_files = sum(1 for f in files if f.is_large)

        return {
            "total_files": len(files),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "large_files": large_files,
            "watched_files": len(self._watched_files),
            "is_paused": self._paused,
            "is_running": self._running,
        }


class LogBuffer:
    """Circular buffer for recent log lines."""

    def __init__(self, max_lines: int = 1000) -> None:
        """Initialize buffer.

        Args:
            max_lines: Maximum number of lines to keep.
        """
        self.max_lines = max_lines
        self._buffer: list[LogLine] = []
        self._lock = asyncio.Lock()

    async def append(self, line: LogLine) -> None:
        """Add a line to the buffer."""
        async with self._lock:
            self._buffer.append(line)
            if len(self._buffer) > self.max_lines:
                self._buffer.pop(0)

    async def get_lines(
        self,
        count: int | None = None,
        service: str | None = None,
    ) -> list[LogLine]:
        """Get lines from buffer.

        Args:
            count: Number of lines to return (None for all).
            service: Filter by service name.

        Returns:
            List of LogLine objects.
        """
        async with self._lock:
            lines = self._buffer.copy()

        if service:
            lines = [l for l in lines if l.service == service]

        if count:
            lines = lines[-count:]

        return lines

    async def clear(self) -> None:
        """Clear the buffer."""
        async with self._lock:
            self._buffer.clear()

    def __len__(self) -> int:
        """Return current buffer size."""
        return len(self._buffer)
