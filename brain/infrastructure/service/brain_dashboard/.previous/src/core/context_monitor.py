"""Context Usage Monitor for Agent Dashboard."""

import json
import os
import logging
from pathlib import Path
from typing import Any
from dataclasses import dataclass

logger = logging.getLogger("agent_dashboard.context_monitor")

# Claude context window size (tokens)
CONTEXT_WINDOW_SIZE = 200000


@dataclass
class ContextUsage:
    """Context usage data for an agent session."""
    session_id: str
    instance_id: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    total_context: int
    context_window: int
    usage_percent: float
    model: str


class ContextMonitor:
    """Monitors context usage by parsing Claude session files."""

    def __init__(
        self,
        projects_dir: str = "/root/.claude/projects/-brain",
        context_window: int = CONTEXT_WINDOW_SIZE,
    ) -> None:
        self.projects_dir = Path(projects_dir)
        self.context_window = context_window
        # Cache: instance_id -> session_id mapping
        self._session_cache: dict[str, str] = {}

    def _parse_session_file(self, session_file: Path) -> dict[str, Any] | None:
        """Parse a session .jsonl file and extract latest usage."""
        if not session_file.exists():
            return None

        latest_usage = None
        latest_model = "unknown"

        try:
            with open(session_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        # Look for message with usage
                        if 'message' in data:
                            msg = data['message']
                            if 'usage' in msg:
                                latest_usage = msg['usage']
                            if 'model' in msg:
                                latest_model = msg['model']
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Error parsing {session_file}: {e}")
            return None

        if latest_usage:
            return {
                'usage': latest_usage,
                'model': latest_model,
                'session_id': session_file.stem,
            }
        return None

    def _find_active_sessions(self) -> list[tuple[str, Path]]:
        """Find active session files (modified recently)."""
        if not self.projects_dir.exists():
            logger.warning(f"Projects dir not found: {self.projects_dir}")
            return []

        sessions = []
        for f in self.projects_dir.glob("*.jsonl"):
            # Get modification time
            mtime = f.stat().st_mtime
            sessions.append((f.stem, f, mtime))

        # Sort by modification time, newest first
        sessions.sort(key=lambda x: x[2], reverse=True)

        # Return session_id and path
        return [(s[0], s[1]) for s in sessions[:20]]  # Limit to 20 most recent

    def get_all_context_usage(self) -> list[ContextUsage]:
        """Get context usage for all active sessions."""
        results = []

        for session_id, session_file in self._find_active_sessions():
            data = self._parse_session_file(session_file)
            if not data:
                continue

            usage = data['usage']

            # Calculate total context
            input_tokens = usage.get('input_tokens', 0)
            output_tokens = usage.get('output_tokens', 0)
            cache_read = usage.get('cache_read_input_tokens', 0)
            cache_creation = usage.get('cache_creation_input_tokens', 0)

            # Total context is approximately cache_read + cache_creation
            total_context = cache_read + cache_creation
            usage_percent = (total_context / self.context_window) * 100 if self.context_window > 0 else 0

            results.append(ContextUsage(
                session_id=session_id,
                instance_id=session_id,  # Will be mapped later
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read,
                cache_creation_tokens=cache_creation,
                total_context=total_context,
                context_window=self.context_window,
                usage_percent=round(usage_percent, 2),
                model=data['model'],
            ))

        return results

    def get_context_for_session(self, session_id: str) -> ContextUsage | None:
        """Get context usage for a specific session."""
        session_file = self.projects_dir / f"{session_id}.jsonl"
        data = self._parse_session_file(session_file)

        if not data:
            return None

        usage = data['usage']
        input_tokens = usage.get('input_tokens', 0)
        output_tokens = usage.get('output_tokens', 0)
        cache_read = usage.get('cache_read_input_tokens', 0)
        cache_creation = usage.get('cache_creation_input_tokens', 0)
        total_context = cache_read + cache_creation
        usage_percent = (total_context / self.context_window) * 100 if self.context_window > 0 else 0

        return ContextUsage(
            session_id=session_id,
            instance_id=session_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_creation,
            total_context=total_context,
            context_window=self.context_window,
            usage_percent=round(usage_percent, 2),
            model=data['model'],
        )

    def map_tmux_to_session(self, tmux_session: str) -> str | None:
        """
        Try to map a tmux session name to a Claude session ID.
        This is heuristic - looks for recently modified sessions.
        """
        # For now, return cached mapping if exists
        if tmux_session in self._session_cache:
            return self._session_cache[tmux_session]

        # TODO: Implement better mapping logic
        # Could parse session files to find matching cwd or other markers
        return None

    def update_session_mapping(self, tmux_session: str, session_id: str) -> None:
        """Update the tmux -> session mapping."""
        self._session_cache[tmux_session] = session_id
