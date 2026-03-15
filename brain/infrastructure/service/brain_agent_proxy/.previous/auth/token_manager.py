"""Token manager for OAuth tokens."""
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


class TokenManager:
    """Manage OAuth tokens."""

    def __init__(self, token_dir: Optional[str] = None):
        self.token_dir = Path(token_dir or os.path.expanduser(
            "~/.local/share/brain_agent_proxy/tokens"
        ))
        self.token_dir.mkdir(parents=True, exist_ok=True)

    def get_token(self, provider: str) -> Optional[Dict[str, Any]]:
        """Get token for provider."""
        token_file = self.token_dir / f"{provider}.json"
        if not token_file.exists():
            return None

        try:
            with open(token_file) as f:
                return json.load(f)
        except Exception:
            return None

    def save_token(self, provider: str, token_data: Dict[str, Any]):
        """Save token for provider."""
        token_file = self.token_dir / f"{provider}.json"
        with open(token_file, "w") as f:
            json.dump(token_data, f, indent=2)

        # Secure the file
        os.chmod(token_file, 0o600)

    def delete_token(self, provider: str):
        """Delete token for provider."""
        token_file = self.token_dir / f"{provider}.json"
        if token_file.exists():
            token_file.unlink()

    def is_token_valid(self, provider: str) -> bool:
        """Check if token is valid."""
        import time

        token = self.get_token(provider)
        if not token:
            return False

        expires_at = token.get("expires_at", 0)
        return expires_at > time.time()
