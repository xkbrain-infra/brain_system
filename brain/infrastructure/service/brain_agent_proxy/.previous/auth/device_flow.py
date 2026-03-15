"""OAuth Device Flow implementation."""
import time
from typing import Any, Dict, Optional, Tuple

import httpx


class DeviceFlow:
    """OAuth Device Flow implementation."""

    def __init__(
        self,
        auth_url: str,
        token_url: str,
        client_id: str,
        scope: str = "",
    ):
        self.auth_url = auth_url
        self.token_url = token_url
        self.client_id = client_id
        self.scope = scope

    async def start_flow(self) -> Tuple[str, str, str]:
        """
        Start device flow.
        Returns: (device_code, user_code, verification_uri)
        """
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.auth_url,
                data={
                    "client_id": self.client_id,
                    "scope": self.scope,
                },
                headers={"Accept": "application/json"},
            )

        if resp.status_code != 200:
            raise ValueError(f"Device flow start failed: {resp.text}")

        data = resp.json()
        return (
            data.get("device_code", ""),
            data.get("user_code", ""),
            data.get("verification_uri", ""),
        )

    async def poll_token(
        self,
        device_code: str,
        interval: int = 5,
        timeout: int = 600,
    ) -> Optional[Dict[str, Any]]:
        """
        Poll for token.
        Returns: token data or None if denied/expired
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self.token_url,
                    data={
                        "client_id": self.client_id,
                        "device_code": device_code,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    },
                    headers={"Accept": "application/json"},
                )

            if resp.status_code != 200:
                error_data = resp.json()
                error = error_data.get("error", "")

                if error == "authorization_pending":
                    time.sleep(interval)
                    continue
                elif error == "slow_down":
                    interval += 1
                    time.sleep(interval)
                    continue
                elif error == "expired_token":
                    return None
                elif error == "access_denied":
                    return None
                else:
                    raise ValueError(f"Token poll error: {error}")

            return resp.json()

        return None


class GitHubDeviceFlow(DeviceFlow):
    """GitHub OAuth Device Flow."""

    def __init__(self, client_id: str = "Iv1.b507a08c87ecfe98"):
        super().__init__(
            auth_url="https://github.com/login/device/code",
            token_url="https://github.com/login/oauth/access_token",
            client_id=client_id,
            scope="read:user",
        )
