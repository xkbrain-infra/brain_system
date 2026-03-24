"""Native Gemini provider adapter."""
import asyncio
import json
import os
import subprocess
import uuid
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from .base import BaseProvider


class GeminiProvider(BaseProvider):
    """Adapter for Google Gemini Generative Language API."""

    def __init__(
        self,
        provider_id: str = "gemini",
        api_key: str = "",
        api_key_env: str = "GEMINI_API_KEY",
        api_base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        oauth_token_file: Optional[str] = None,
        oauth_token_url: str = "",
        oauth_client_id: str = "",
        oauth_client_secret: str = "",
        use_code_assist_oauth: bool = False,
        code_assist_endpoint: str = "https://cloudcode-pa.googleapis.com",
        project_id: str = "",
    ):
        self._provider_id = provider_id
        self._api_key = (api_key or "").strip()
        self._api_key_env = api_key_env
        self._api_base_url = api_base_url.rstrip("/")
        self._oauth_token_file = oauth_token_file or "~/.local/share/brain_agent_proxy/tokens/gemini_oauth_device.json"
        self._oauth_token_url = oauth_token_url.strip() or "https://oauth2.googleapis.com/token"
        self._oauth_client_id = oauth_client_id.strip()
        self._oauth_client_secret = oauth_client_secret.strip()
        self._use_code_assist_oauth = use_code_assist_oauth
        self._code_assist_endpoint = code_assist_endpoint.rstrip("/")
        self._project_id = project_id.strip()

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def provider_type(self) -> str:
        return "gemini"

    def _resolve_api_key(self) -> str:
        key = self._api_key or os.environ.get(self._api_key_env, "").strip()
        # Backward-compat: if env has OAuth bearer token, accept it as auth header token.
        if not key:
            oauth_env = os.environ.get("GEMINI_OAUTH_ACCESS_TOKEN", "").strip()
            if oauth_env:
                return oauth_env
        if not key:
            raise ValueError(
                f"Missing Gemini credential: run 'gcloud auth application-default login' "
                f"or 'brain_agentctl auth --provider {self._provider_id}' "
                f"or set config.providers.{self._provider_id}.api_key.api_key or env {self._api_key_env}"
            )
        return key

    def _resolve_oauth_bearer(self) -> str:
        env_token = os.environ.get("GEMINI_OAUTH_ACCESS_TOKEN", "").strip()
        if env_token:
            return env_token

        token_file = Path(self._oauth_token_file).expanduser()
        if not token_file.exists():
            return self._resolve_gcloud_adc_token()
        try:
            with open(token_file) as f:
                data = json.load(f)
            access_token = str(data.get("access_token", "") or "").strip()
            expires_at = int(data.get("expires_at", 0) or 0)
            if not access_token:
                refreshed = self._refresh_oauth_token(data, token_file)
                if refreshed:
                    return refreshed
                return self._resolve_gcloud_adc_token()
            # Refresh ahead-of-expiry to avoid mid-request token expiration.
            if expires_at and expires_at <= int(time.time()) + 60:
                refreshed = self._refresh_oauth_token(data, token_file)
                if refreshed:
                    return refreshed
                return self._resolve_gcloud_adc_token()
            return access_token
        except Exception:
            return self._resolve_gcloud_adc_token()

    def _refresh_oauth_token(self, token_data: Dict[str, Any], token_file: Path) -> str:
        refresh_token = str(token_data.get("refresh_token", "") or "").strip()
        if not refresh_token or not self._oauth_client_id:
            return ""

        body: Dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self._oauth_client_id,
        }
        if self._oauth_client_secret:
            body["client_secret"] = self._oauth_client_secret
        try:
            resp = httpx.post(
                self._oauth_token_url,
                data=body,
                headers={"Accept": "application/json"},
                timeout=20.0,
            )
            if resp.status_code != 200:
                return ""
            refreshed = resp.json()
            access_token = str(refreshed.get("access_token", "") or "").strip()
            if not access_token:
                return ""
            expires_in = int(refreshed.get("expires_in", 3600) or 3600)
            out = {
                "access_token": access_token,
                "refresh_token": str(refreshed.get("refresh_token", "") or "").strip() or refresh_token,
                "token_type": str(refreshed.get("token_type", "bearer") or "bearer"),
                "scope": str(refreshed.get("scope", token_data.get("scope", "")) or token_data.get("scope", "")),
                "expires_at": int(time.time()) + expires_in,
                "raw": refreshed,
            }
            token_file.parent.mkdir(parents=True, exist_ok=True)
            with open(token_file, "w") as f:
                json.dump(out, f, indent=2)
            os.chmod(token_file, 0o600)
            return access_token
        except Exception:
            return ""

    @staticmethod
    def _resolve_gcloud_adc_token() -> str:
        for cmd in (
            ["gcloud", "auth", "application-default", "print-access-token"],
            ["gcloud", "auth", "print-access-token"],
        ):
            try:
                out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=8).decode("utf-8").strip()
                if out:
                    return out
            except Exception:
                continue
        return ""

    @staticmethod
    def _normalize_model(model: str) -> str:
        m = (model or "").strip()
        if m.startswith("models/"):
            return m
        return f"models/{m}"

    @staticmethod
    def _extract_text_from_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            ctype = str(content.get("type", "") or "")
            if ctype == "text":
                return str(content.get("text", "") or "")
            if ctype == "thinking":
                return str(content.get("thinking", "") or "")
            if ctype == "tool_result":
                return GeminiProvider._extract_text_from_content(content.get("content", ""))
            return GeminiProvider._extract_text_from_content(content.get("content", ""))
        if isinstance(content, list):
            parts = []
            for block in content:
                part = GeminiProvider._extract_text_from_content(block)
                if part:
                    parts.append(part)
            return " ".join(parts)
        return str(content)

    @classmethod
    def _to_gemini_parts(cls, content: Any) -> List[Dict[str, Any]]:
        if isinstance(content, list):
            parts: List[Dict[str, Any]] = []
            for item in content:
                parts.extend(cls._to_gemini_parts(item))
            return parts

        if isinstance(content, dict):
            ctype = str(content.get("type", "") or "")
            if ctype == "text":
                text = str(content.get("text", "") or "")
                return [{"text": text}] if text else []
            text = cls._extract_text_from_content(content)
            return [{"text": text}] if text else []

        text = cls._extract_text_from_content(content)
        return [{"text": text}] if text else []

    @classmethod
    def _convert_tools(cls, tools: Any) -> Optional[List[Dict[str, Any]]]:
        if not isinstance(tools, list):
            return None
        function_declarations: List[Dict[str, Any]] = []
        for item in tools:
            if not isinstance(item, dict):
                continue

            fn = item.get("function")
            if isinstance(fn, dict):
                name = str(fn.get("name", "") or "").strip()
                if not name:
                    continue
                function_declarations.append(
                    {
                        "name": name,
                        "description": str(fn.get("description", "") or ""),
                        "parameters": cls._sanitize_schema_for_gemini(
                            fn.get("parameters") or {"type": "object", "properties": {}}
                        ),
                    }
                )
                continue

            name = str(item.get("name", "") or "").strip()
            if not name:
                continue
            function_declarations.append(
                {
                    "name": name,
                    "description": str(item.get("description", "") or ""),
                    "parameters": cls._sanitize_schema_for_gemini(
                        item.get("input_schema") or {"type": "object", "properties": {}}
                    ),
                }
            )

        if not function_declarations:
            return None
        return [{"functionDeclarations": function_declarations}]

    @classmethod
    def _sanitize_schema_for_gemini(cls, schema: Any) -> Any:
        """Drop JSON-Schema metadata keys unsupported by Gemini tool schema."""
        if isinstance(schema, list):
            return [cls._sanitize_schema_for_gemini(item) for item in schema]
        if isinstance(schema, dict):
            out: Dict[str, Any] = {}
            for key, value in schema.items():
                # Gemini functionDeclaration.parameters rejects "$schema" and similar keys.
                if isinstance(key, str) and key.startswith("$"):
                    continue
                out[key] = cls._sanitize_schema_for_gemini(value)
            return out
        return schema

    @staticmethod
    def _convert_tool_choice(tool_choice: Any) -> Optional[Dict[str, Any]]:
        if tool_choice is None:
            return None
        mode = None
        allowed_names = None
        if isinstance(tool_choice, str):
            s = tool_choice.lower()
            if s == "auto":
                mode = "AUTO"
            elif s in ("none", "off"):
                mode = "NONE"
            elif s in ("required", "any"):
                mode = "ANY"
        elif isinstance(tool_choice, dict):
            t = str(tool_choice.get("type", "") or "").lower()
            if t in ("function", "tool"):
                mode = "ANY"
                name = ""
                fn = tool_choice.get("function")
                if isinstance(fn, dict):
                    name = str(fn.get("name", "") or "").strip()
                if not name:
                    name = str(tool_choice.get("name", "") or "").strip()
                if name:
                    allowed_names = [name]
            elif t == "auto":
                mode = "AUTO"
            elif t == "none":
                mode = "NONE"

        if not mode:
            return None
        out: Dict[str, Any] = {"functionCallingConfig": {"mode": mode}}
        if allowed_names:
            out["functionCallingConfig"]["allowedFunctionNames"] = allowed_names
        return out

    @classmethod
    def _build_payload(cls, request: Dict[str, Any], protocol: str) -> Dict[str, Any]:
        system_text = ""
        contents: List[Dict[str, Any]] = []

        if protocol == "messages":
            system = request.get("system")
            if system is not None:
                system_text = cls._extract_text_from_content(system)
            for msg in request.get("messages", []) or []:
                if not isinstance(msg, dict):
                    continue
                role = "model" if str(msg.get("role", "user")) == "assistant" else "user"
                parts = cls._to_gemini_parts(msg.get("content", ""))
                if parts:
                    contents.append({"role": role, "parts": parts})
        elif protocol == "chat_completions":
            for msg in request.get("messages", []) or []:
                if not isinstance(msg, dict):
                    continue
                raw_role = str(msg.get("role", "user"))
                if raw_role == "system":
                    system_text = cls._extract_text_from_content(msg.get("content", ""))
                    continue
                role = "model" if raw_role == "assistant" else "user"
                parts = cls._to_gemini_parts(msg.get("content", ""))
                if parts:
                    contents.append({"role": role, "parts": parts})
        else:  # responses
            for item in request.get("input", []) or []:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "message":
                    raw_role = str(item.get("role", "user"))
                    if raw_role == "system":
                        system_text = cls._extract_text_from_content(item.get("content", ""))
                        continue
                    role = "model" if raw_role == "assistant" else "user"
                    parts = cls._to_gemini_parts(item.get("content", ""))
                    if parts:
                        contents.append({"role": role, "parts": parts})
                elif item.get("type") == "text":
                    text = str(item.get("text", "") or "")
                    if text:
                        contents.append({"role": "user", "parts": [{"text": text}]})

        payload: Dict[str, Any] = {"contents": contents or [{"role": "user", "parts": [{"text": ""}]}]}
        if system_text:
            payload["system_instruction"] = {"parts": [{"text": system_text}]}

        generation_config: Dict[str, Any] = {}
        temperature = request.get("temperature")
        if temperature is not None:
            generation_config["temperature"] = temperature
        max_tokens = request.get("max_tokens")
        if max_tokens is not None:
            generation_config["maxOutputTokens"] = max_tokens
        if generation_config:
            payload["generationConfig"] = generation_config

        tools = cls._convert_tools(request.get("tools"))
        if tools:
            payload["tools"] = tools
            tool_config = cls._convert_tool_choice(request.get("tool_choice"))
            if tool_config:
                payload["toolConfig"] = tool_config

        return payload

    @staticmethod
    def _code_assist_headers(access_token: str, model: str = "gemini") -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "User-Agent": f"GeminiCLI/0.1 ({model})",
            "X-Goog-Api-Client": "gl-node/22.17.0",
            "Client-Metadata": "ideType=IDE_UNSPECIFIED,platform=PLATFORM_UNSPECIFIED,pluginType=GEMINI",
        }

    async def _resolve_code_assist_project(self, access_token: str) -> str:
        configured = (
            self._project_id
            or os.environ.get("OPENCODE_GEMINI_PROJECT_ID", "").strip()
            or os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
            or os.environ.get("GOOGLE_CLOUD_PROJECT_ID", "").strip()
        )
        if configured:
            return configured

        metadata = {
            "ideType": "IDE_UNSPECIFIED",
            "platform": "PLATFORM_UNSPECIFIED",
            "pluginType": "GEMINI",
        }
        url = f"{self._code_assist_endpoint}/v1internal:loadCodeAssist"
        headers = self._code_assist_headers(access_token, "loadCodeAssist")
        body = {"metadata": metadata}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=body)
        if resp.status_code != 200:
            raise ValueError(
                "Gemini OAuth requires a Google Cloud project. Set GOOGLE_CLOUD_PROJECT "
                "or OPENCODE_GEMINI_PROJECT_ID."
            )
        data = resp.json()
        project = data.get("cloudaicompanionProject")
        if isinstance(project, str) and project:
            return project
        if isinstance(project, dict):
            pid = str(project.get("id", "") or "").strip()
            if pid:
                return pid

        # Try free-tier onboarding to auto-provision a managed project (Gemini CLI behavior).
        onboard_url = f"{self._code_assist_endpoint}/v1internal:onboardUser"
        onboard_body = {"tierId": "free-tier", "metadata": metadata}
        async with httpx.AsyncClient(timeout=60.0) as client:
            onboard_resp = await client.post(onboard_url, headers=headers, json=onboard_body)
        if onboard_resp.status_code == 200:
            try:
                op = onboard_resp.json()
                # Poll long-running operation if needed.
                if isinstance(op, dict) and not bool(op.get("done")) and op.get("name"):
                    op_name = str(op.get("name", "") or "").strip()
                    if op_name:
                        op_url = f"{self._code_assist_endpoint}/v1internal/{op_name}"
                        for _ in range(8):
                            await asyncio.sleep(2)
                            async with httpx.AsyncClient(timeout=30.0) as client:
                                poll_resp = await client.get(op_url, headers=headers)
                            if poll_resp.status_code != 200:
                                break
                            op = poll_resp.json()
                            if isinstance(op, dict) and bool(op.get("done")):
                                break
                # Load again after onboarding.
                async with httpx.AsyncClient(timeout=30.0) as client:
                    reload_resp = await client.post(url, headers=headers, json=body)
                if reload_resp.status_code == 200:
                    reload_data = reload_resp.json()
                    reload_project = reload_data.get("cloudaicompanionProject")
                    if isinstance(reload_project, str) and reload_project:
                        return reload_project
                    if isinstance(reload_project, dict):
                        pid = str(reload_project.get("id", "") or "").strip()
                        if pid:
                            return pid
            except Exception:
                pass

        current_tier = (data.get("currentTier") or {}).get("id")
        if current_tier:
            raise ValueError(
                "Gemini OAuth requires project binding for Code Assist. "
                "Set GOOGLE_CLOUD_PROJECT or OPENCODE_GEMINI_PROJECT_ID."
            )
        raise ValueError(
            "Unable to resolve Gemini Code Assist project. "
            "Set GOOGLE_CLOUD_PROJECT or OPENCODE_GEMINI_PROJECT_ID."
        )

    async def _forward_code_assist_once(self, request: Dict[str, Any], protocol: str) -> Dict[str, Any]:
        access_token = self._resolve_oauth_bearer()
        if not access_token:
            raise ValueError(
                "Missing Gemini OAuth credential for Code Assist. "
                "Run 'brain_agentctl auth --provider gemini' first."
            )
        raw_model = str(request.get("model", "") or "").strip()
        model_name = raw_model[7:] if raw_model.startswith("models/") else raw_model
        if not model_name:
            raise ValueError("Gemini model is required")

        project_id = await self._resolve_code_assist_project(access_token)
        inner = self._build_payload(request, protocol)
        wrapped = {
            "project": project_id,
            "model": model_name,
            "user_prompt_id": str(uuid.uuid4()),
            "request": inner,
        }
        url = f"{self._code_assist_endpoint}/v1internal:generateContent"
        headers = self._code_assist_headers(access_token, model_name)

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=wrapped, headers=headers)
        if resp.status_code != 200:
            raise ValueError(f"Gemini Code Assist error: {resp.status_code} {resp.text}")
        data = resp.json()
        if isinstance(data, dict) and isinstance(data.get("response"), dict):
            return data["response"]
        return data

    async def _forward_code_assist_stream(self, request: Dict[str, Any], protocol: str):
        access_token = self._resolve_oauth_bearer()
        if not access_token:
            raise ValueError(
                "Missing Gemini OAuth credential for Code Assist. "
                "Run 'brain_agentctl auth --provider gemini' first."
            )
        raw_model = str(request.get("model", "") or "").strip()
        model_name = raw_model[7:] if raw_model.startswith("models/") else raw_model
        if not model_name:
            raise ValueError("Gemini model is required")

        project_id = await self._resolve_code_assist_project(access_token)
        inner = self._build_payload(request, protocol)
        wrapped = {
            "project": project_id,
            "model": model_name,
            "user_prompt_id": str(uuid.uuid4()),
            "request": inner,
        }
        url = f"{self._code_assist_endpoint}/v1internal:streamGenerateContent?alt=sse"
        headers = self._code_assist_headers(access_token, model_name)
        headers["Accept"] = "text/event-stream"

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, json=wrapped, headers=headers) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", "ignore")
                    raise ValueError(f"Gemini Code Assist error: {resp.status_code} {body}")
                async for chunk in resp.aiter_bytes():
                    if chunk:
                        yield chunk

    @staticmethod
    def _parse_gemini_response(result: Dict[str, Any]) -> Dict[str, Any]:
        candidate = (result.get("candidates") or [{}])[0] or {}
        content = candidate.get("content", {}) or {}
        parts = content.get("parts", []) or []
        blocks: List[Dict[str, Any]] = []
        text = ""
        for part in parts:
            if not isinstance(part, dict):
                continue
            if "text" in part:
                chunk = str(part.get("text", "") or "")
                if chunk:
                    text += chunk
            elif "functionCall" in part and isinstance(part.get("functionCall"), dict):
                fc = part.get("functionCall") or {}
                name = str(fc.get("name", "") or "")
                args = fc.get("args")
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": f"toolu_{uuid.uuid4().hex[:8]}",
                        "name": name,
                        "input": args if isinstance(args, dict) else {},
                    }
                )
        if text:
            blocks.insert(0, {"type": "text", "text": text})
        if not blocks:
            blocks = [{"type": "text", "text": ""}]

        usage = result.get("usageMetadata", {}) or {}
        return {
            "content_blocks": blocks,
            "text": text,
            "input_tokens": int(usage.get("promptTokenCount", 0) or 0),
            "output_tokens": int(usage.get("candidatesTokenCount", 0) or 0),
            "stop_reason": "end_turn",
        }

    async def forward(self, request: Dict[str, Any], protocol: str = "messages") -> Dict[str, Any]:
        bearer = self._resolve_oauth_bearer()
        if bearer and self._use_code_assist_oauth:
            result = await self._forward_code_assist_once(request, protocol)
            if not isinstance(result, dict):
                raise ValueError("Invalid Gemini Code Assist response")
            parsed = self._parse_gemini_response(result)
            response_id = f"gemini_{uuid.uuid4().hex[:12]}"
            model_name = str(request.get("model", ""))
            if protocol == "chat_completions":
                message: Dict[str, Any] = {"role": "assistant", "content": parsed["text"]}
                tool_uses = [b for b in parsed["content_blocks"] if b.get("type") == "tool_use"]
                if tool_uses:
                    message["tool_calls"] = [
                        {
                            "id": b.get("id"),
                            "type": "function",
                            "function": {
                                "name": b.get("name", ""),
                                "arguments": json.dumps(b.get("input", {}), ensure_ascii=False),
                            },
                        }
                        for b in tool_uses
                    ]
                return {
                    "id": response_id,
                    "model": model_name,
                    "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                    "input_tokens": parsed["input_tokens"],
                    "output_tokens": parsed["output_tokens"],
                }
            if protocol == "responses":
                return {
                    "id": response_id,
                    "model": model_name,
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": parsed["text"]}]}],
                    "usage": {"input_tokens": parsed["input_tokens"], "output_tokens": parsed["output_tokens"]},
                    "messages": [],
                    "content": parsed["text"],
                    "input_tokens": parsed["input_tokens"],
                    "output_tokens": parsed["output_tokens"],
                }
            return {
                "id": response_id,
                "model": model_name,
                "content": parsed["content_blocks"],
                "stop_reason": parsed["stop_reason"],
                "input_tokens": parsed["input_tokens"],
                "output_tokens": parsed["output_tokens"],
            }

        api_key = self._resolve_api_key() if not bearer else ""
        model = self._normalize_model(str(request.get("model", "")))
        payload = self._build_payload(request, protocol)

        url = f"{self._api_base_url}/{model}:generateContent"
        headers = {"Content-Type": "application/json"}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        else:
            url = f"{url}?key={api_key}"
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            raise ValueError(f"Gemini API error: {resp.status_code} {resp.text}")

        result = resp.json()
        parsed = self._parse_gemini_response(result)
        response_id = f"gemini_{uuid.uuid4().hex[:12]}"
        model_name = str(request.get("model", ""))

        if protocol == "chat_completions":
            message: Dict[str, Any] = {"role": "assistant", "content": parsed["text"]}
            tool_uses = [b for b in parsed["content_blocks"] if b.get("type") == "tool_use"]
            if tool_uses:
                message["tool_calls"] = [
                    {
                        "id": b.get("id"),
                        "type": "function",
                        "function": {
                            "name": b.get("name", ""),
                            "arguments": json.dumps(b.get("input", {}), ensure_ascii=False),
                        },
                    }
                    for b in tool_uses
                ]
            return {
                "id": response_id,
                "model": model_name,
                "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                "input_tokens": parsed["input_tokens"],
                "output_tokens": parsed["output_tokens"],
            }

        if protocol == "responses":
            return {
                "id": response_id,
                "model": model_name,
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": parsed["text"]}],
                    }
                ],
                "usage": {
                    "input_tokens": parsed["input_tokens"],
                    "output_tokens": parsed["output_tokens"],
                },
                "messages": [],
                "content": parsed["text"],
                "input_tokens": parsed["input_tokens"],
                "output_tokens": parsed["output_tokens"],
            }

        return {
            "id": response_id,
            "model": model_name,
            "content": parsed["content_blocks"],
            "stop_reason": parsed["stop_reason"],
            "input_tokens": parsed["input_tokens"],
            "output_tokens": parsed["output_tokens"],
        }

    async def health_check(self) -> bool:
        """Basic Gemini upstream health check."""
        bearer = self._resolve_oauth_bearer()
        api_key = self._api_key or os.environ.get(self._api_key_env, "").strip()
        if not bearer and not api_key:
            return False
        if bearer and self._use_code_assist_oauth:
            try:
                await self._resolve_code_assist_project(bearer)
                return True
            except Exception:
                return False
        model = "models/gemini-2.5-pro"
        url = f"{self._api_base_url}/{model}:generateContent"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
            "generationConfig": {"maxOutputTokens": 1},
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = {"Content-Type": "application/json"}
                if bearer:
                    headers["Authorization"] = f"Bearer {bearer}"
                else:
                    url = f"{url}?key={api_key}"
                resp = await client.post(url, json=payload, headers=headers)
            return resp.status_code == 200
        except Exception:
            return False

    async def forward_stream(self, request: Dict[str, Any], protocol: str = "messages"):
        bearer = self._resolve_oauth_bearer()
        if bearer and self._use_code_assist_oauth:
            response_id = f"gemini_{uuid.uuid4().hex[:12]}"
            model_name = str(request.get("model", ""))
            emitted_text = ""
            usage: Dict[str, Any] = {}
            async for chunk in self._forward_code_assist_stream(request, protocol):
                text = chunk.decode("utf-8", "ignore")
                for line in text.splitlines():
                    s = line.strip()
                    if not s.startswith("data:"):
                        continue
                    data = s[5:].strip()
                    if not data:
                        continue
                    try:
                        obj = json.loads(data)
                    except Exception:
                        continue
                    if isinstance(obj, dict) and isinstance(obj.get("response"), dict):
                        obj = obj["response"]
                    usage = obj.get("usageMetadata", {}) or usage
                    candidate = (obj.get("candidates") or [{}])[0] or {}
                    content = candidate.get("content", {}) or {}
                    parts = content.get("parts", []) or []
                    current_text = ""
                    for part in parts:
                        if isinstance(part, dict) and "text" in part:
                            current_text += str(part.get("text", "") or "")
                    if current_text:
                        delta = current_text
                        if current_text.startswith(emitted_text):
                            delta = current_text[len(emitted_text):]
                        emitted_text = current_text
                        if delta:
                            yield (
                                "data: "
                                + json.dumps(
                                    {
                                        "id": response_id,
                                        "model": model_name,
                                        "choices": [{"index": 0, "delta": {"content": delta}, "finish_reason": None}],
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n\n"
                            ).encode("utf-8")
            yield (
                "data: "
                + json.dumps(
                    {
                        "id": response_id,
                        "model": model_name,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                        "usage": {
                            "prompt_tokens": int(usage.get("promptTokenCount", 0) or 0),
                            "completion_tokens": int(usage.get("candidatesTokenCount", 0) or 0),
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n\n"
            ).encode("utf-8")
            yield b"data: [DONE]\n\n"
            return

        api_key = self._resolve_api_key() if not bearer else ""
        model = self._normalize_model(str(request.get("model", "")))
        payload = self._build_payload(request, protocol)
        url = f"{self._api_base_url}/{model}:streamGenerateContent?alt=sse"
        headers = {"Content-Type": "application/json"}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        else:
            url = f"{url}&key={api_key}"

        response_id = f"gemini_{uuid.uuid4().hex[:12]}"
        model_name = str(request.get("model", ""))
        emitted_text = ""
        usage: Dict[str, Any] = {}

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", "ignore")
                    raise ValueError(f"Gemini API error: {resp.status_code} {body}")

                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    s = line.strip()
                    if not s.startswith("data:"):
                        continue
                    data = s[5:].strip()
                    if not data:
                        continue
                    try:
                        obj = json.loads(data)
                    except Exception:
                        continue

                    usage = obj.get("usageMetadata", {}) or usage
                    candidate = (obj.get("candidates") or [{}])[0] or {}
                    content = candidate.get("content", {}) or {}
                    parts = content.get("parts", []) or []

                    current_text = ""
                    for part in parts:
                        if isinstance(part, dict) and "text" in part:
                            current_text += str(part.get("text", "") or "")

                    if current_text:
                        delta = current_text
                        if current_text.startswith(emitted_text):
                            delta = current_text[len(emitted_text):]
                        emitted_text = current_text
                        if delta:
                            yield (
                                "data: "
                                + json.dumps(
                                    {
                                        "id": response_id,
                                        "model": model_name,
                                        "choices": [{"index": 0, "delta": {"content": delta}, "finish_reason": None}],
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n\n"
                            ).encode("utf-8")

                yield (
                    "data: "
                    + json.dumps(
                        {
                            "id": response_id,
                            "model": model_name,
                            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                            "usage": {
                                "prompt_tokens": int(usage.get("promptTokenCount", 0) or 0),
                                "completion_tokens": int(usage.get("candidatesTokenCount", 0) or 0),
                            },
                        },
                        ensure_ascii=False,
                    )
                    + "\n\n"
                ).encode("utf-8")
                yield b"data: [DONE]\n\n"
