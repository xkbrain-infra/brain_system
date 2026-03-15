"""Health checker."""
import json
import os
from typing import Dict, Any


class HealthChecker:
    """Health check utilities."""

    @staticmethod
    async def check_copilot_auth() -> bool:
        """Check if at least one Copilot auth token source exists."""
        try:
            token_dir = os.path.expanduser("~/.local/share/brain_agent_proxy/tokens")
            for name in ("copilot.json", "github_oauth.json"):
                path = os.path.join(token_dir, name)
                if not os.path.exists(path):
                    continue
                with open(path) as f:
                    data = json.load(f) or {}
                if str(data.get("access_token", "") or data.get("github_token", "")).strip():
                    return True
            return False
        except Exception:
            return False

    @staticmethod
    async def check() -> Dict[str, Any]:
        """Perform health check."""
        copilot_status = "unknown"
        try:
            copilot_auth_ok = await HealthChecker.check_copilot_auth()
            copilot_status = "healthy" if copilot_auth_ok else "missing_auth"
        except Exception:
            copilot_status = "error"

        return {
            "status": "healthy" if copilot_status in ("healthy", "missing_auth") else "degraded",
            "services": {
                "brain_agent_proxy": "healthy",
                "copilot_direct": copilot_status,
            },
        }
