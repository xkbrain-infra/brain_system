"""Claude CLI-backed provider using local Claude OAuth login."""
import asyncio
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from .base import BaseProvider


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        ctype = str(content.get("type", "") or "")
        if ctype == "text":
            return str(content.get("text", "") or "")
        if ctype == "thinking":
            return ""
        if ctype == "tool_use":
            tool_name = str(content.get("name", "") or "")
            tool_id = str(content.get("id", "") or "")
            tool_input = json.dumps(content.get("input", {}) or {}, ensure_ascii=False, indent=2)
            return f"<tool_use name={tool_name!r} id={tool_id!r}>\n{tool_input}\n</tool_use>"
        if ctype == "tool_result":
            tool_use_id = str(content.get("tool_use_id", "") or "")
            inner = _content_to_text(content.get("content", ""))
            return f"<tool_result tool_use_id={tool_use_id!r}>\n{inner}\n</tool_result>"
        return _content_to_text(content.get("content", ""))
    if isinstance(content, list):
        parts = [_content_to_text(item) for item in content]
        return "\n".join(part for part in parts if part)
    return str(content)


def _extract_paths(text: str) -> list[Path]:
    candidates: list[Path] = []
    for match in re.finditer(r"(/[A-Za-z0-9._/\-]+)", text or ""):
        raw = match.group(1).rstrip(".,:;)]}>\"'")
        if not raw.startswith("/"):
            continue
        path = Path(raw)
        if path.exists():
            candidates.append(path if path.is_dir() else path.parent)
    return candidates


def _claude_auth_status(cli_path: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [cli_path, "auth", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except FileNotFoundError:
        return False, "Claude CLI is not installed or not in PATH."
    except Exception as exc:
        return False, f"Unable to determine Claude auth status: {exc}"

    raw = (proc.stdout or proc.stderr or "").strip()
    if raw:
        try:
            data = json.loads(raw)
        except Exception:
            if proc.returncode == 0:
                return True, ""
            return False, f"Unable to parse `claude auth status --json`: {raw}"

        if bool(data.get("loggedIn")):
            return True, ""

        auth_method = str(data.get("authMethod") or "none").strip() or "none"
        api_provider = str(data.get("apiProvider") or "firstParty").strip() or "firstParty"
        return (
            False,
            "Claude provider backend is unavailable: local Claude CLI is not authenticated "
            f"(authMethod={auth_method}, apiProvider={api_provider}). "
            "Run `claude auth login` on the host first.",
        )

    if proc.returncode == 0:
        return True, ""
    return False, f"`claude auth status --json` exited with code {proc.returncode}"


def _parse_stream_events(stdout_text: str) -> Dict[str, Any]:
    assistant_message: Optional[Dict[str, Any]] = None
    result_event: Optional[Dict[str, Any]] = None
    api_retries: list[str] = []
    raw_errors: list[str] = []

    for raw_line in stdout_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except Exception:
            continue
        etype = str(event.get("type", "") or "")
        if etype == "assistant":
            msg = event.get("message")
            if isinstance(msg, dict):
                assistant_message = msg
        elif etype == "result":
            result_event = event
        elif etype == "system" and str(event.get("subtype", "") or "") == "api_retry":
            status = event.get("error_status")
            error = str(event.get("error", "") or "").strip()
            if status:
                api_retries.append(f"{status} {error}".strip())
            elif error:
                api_retries.append(error)
        elif etype == "error":
            message = str(event.get("message", "") or event.get("error", "") or "").strip()
            if message:
                raw_errors.append(message)

    return {
        "assistant_message": assistant_message,
        "result_event": result_event,
        "api_retries": api_retries,
        "raw_errors": raw_errors,
    }


def _format_cli_failure(parsed: Dict[str, Any], stderr_text: str, returncode: int) -> str:
    if stderr_text:
        return stderr_text

    raw_errors = parsed.get("raw_errors") or []
    if raw_errors:
        return raw_errors[-1]

    retries = parsed.get("api_retries") or []
    if retries:
        summary = ", ".join(retries[-3:])
        return f"Claude CLI upstream retries failed: {summary}"

    result_event = parsed.get("result_event") or {}
    result_text = str(result_event.get("result", "") or "").strip()
    if result_text:
        return result_text

    return f"claude CLI exited with code {returncode}"


def _sse_bytes(event_type: str, payload: Dict[str, Any]) -> bytes:
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


class ClaudeCLIProvider(BaseProvider):
    """Provider that delegates requests to local `claude -p`."""

    def __init__(
        self,
        provider_id: str = "claude",
        workdir: Optional[str] = None,
        permission_mode: str = "default",
        cli_path: Optional[str] = None,
    ):
        self._provider_id = provider_id
        self._workdir = workdir or ""
        requested_permission_mode = permission_mode or "default"
        # Claude CLI rejects bypassPermissions when invoked as root in print mode.
        if requested_permission_mode == "bypassPermissions" and hasattr(os, "geteuid") and os.geteuid() == 0:
            requested_permission_mode = "default"
        self._permission_mode = requested_permission_mode
        self._cli_path = cli_path or shutil.which("claude") or "claude"

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def provider_type(self) -> str:
        return "claude_cli"

    async def forward(self, request: Dict[str, Any], protocol: str = "messages") -> Dict[str, Any]:
        if protocol != "messages":
            raise ValueError("Claude CLI provider currently supports messages protocol only")

        ok, detail = _claude_auth_status(self._cli_path)
        if not ok:
            raise ValueError(detail)

        model = self._normalize_model(str(request.get("model", "") or "claude-sonnet-4-6"))
        prompt = self._build_prompt(request)
        workdir = self._resolve_workdir(request)
        cmd, env = self._build_cli_cmd(model, workdir, include_partial_messages=False)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self._exec_cwd()),
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(prompt.encode("utf-8"))
        stderr_text = stderr.decode("utf-8", "ignore").strip()
        stdout_text = stdout.decode("utf-8", "ignore")
        parsed = _parse_stream_events(stdout_text)
        if proc.returncode != 0:
            raise ValueError(_format_cli_failure(parsed, stderr_text, proc.returncode))

        assistant_message = parsed.get("assistant_message")
        result_event = parsed.get("result_event")

        if assistant_message is None:
            detail = _format_cli_failure(parsed, stderr_text, proc.returncode)
            raise ValueError(f"Claude CLI provider produced no assistant message: {detail}")

        content = []
        for block in assistant_message.get("content", []) or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "thinking":
                continue
            content.append(block)
        if not content:
            result_text = str((result_event or {}).get("result", "") or "").strip()
            if result_text:
                content = [{"type": "text", "text": result_text}]

        usage = (result_event or {}).get("usage", {}) or assistant_message.get("usage", {}) or {}
        stop_reason = str((result_event or {}).get("stop_reason", "") or assistant_message.get("stop_reason", "") or "end_turn")

        return {
            "id": assistant_message.get("id", f"msg_{uuid.uuid4().hex[:8]}"),
            "model": request.get("model", model),
            "content": content,
            "stop_reason": stop_reason,
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
            "cache_read_input_tokens": int(usage.get("cache_read_input_tokens", 0) or 0),
            "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens", 0) or 0),
        }

    async def forward_stream(self, request: Dict[str, Any], protocol: str = "messages"):
        if protocol != "messages":
            raise ValueError("Claude CLI provider currently supports messages protocol only")

        ok, detail = _claude_auth_status(self._cli_path)
        if not ok:
            raise ValueError(detail)

        model = self._normalize_model(str(request.get("model", "") or "claude-sonnet-4-6"))
        prompt = self._build_prompt(request)
        workdir = self._resolve_workdir(request)
        cmd, env = self._build_cli_cmd(model, workdir, include_partial_messages=True)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            prompt,
            cwd=str(self._exec_cwd()),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert proc.stdout is not None
        assert proc.stderr is not None

        async def _iter():
            emitted = 0
            retries: list[str] = []
            raw_errors: list[str] = []

            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", "ignore").strip()
                if not text:
                    continue
                try:
                    event = json.loads(text)
                except Exception:
                    continue

                etype = str(event.get("type", "") or "")
                if etype == "stream_event":
                    inner = event.get("event")
                    if isinstance(inner, dict):
                        inner_type = str(inner.get("type", "") or "")
                        if inner_type:
                            emitted += 1
                            yield _sse_bytes(inner_type, inner)
                elif etype == "system" and str(event.get("subtype", "") or "") == "api_retry":
                    status = event.get("error_status")
                    error = str(event.get("error", "") or "").strip()
                    if status:
                        retries.append(f"{status} {error}".strip())
                    elif error:
                        retries.append(error)
                elif etype == "error":
                    message = str(event.get("message", "") or event.get("error", "") or "").strip()
                    if message:
                        raw_errors.append(message)

            stderr_text = (await proc.stderr.read()).decode("utf-8", "ignore").strip()
            returncode = await proc.wait()
            if returncode != 0:
                parsed = {
                    "api_retries": retries,
                    "raw_errors": raw_errors,
                    "result_event": {},
                }
                raise ValueError(_format_cli_failure(parsed, stderr_text, returncode))
            if emitted == 0:
                parsed = {
                    "api_retries": retries,
                    "raw_errors": raw_errors,
                    "result_event": {},
                }
                raise ValueError(_format_cli_failure(parsed, stderr_text, returncode))

        return _iter()

    async def health_check(self) -> bool:
        ok, _ = _claude_auth_status(self._cli_path)
        return ok

    def _build_cli_cmd(self, model: str, workdir: Path, *, include_partial_messages: bool) -> tuple[list[str], Dict[str, str]]:
        env = os.environ.copy()
        for key in (
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_AUTH_TOKEN",
            "BRAIN_TRANSPORT_MODE",
            "BRAIN_AGENT_PROXY_URL",
        ):
            env.pop(key, None)
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"

        cmd = [
            self._cli_path,
            "-p",
            "--model",
            model,
            "--setting-sources",
            "user",
            "--permission-mode",
            self._permission_mode,
            "--input-format",
            "text",
            "--output-format",
            "stream-json",
            "--verbose",
            "--system-prompt",
            self._base_system_prompt(),
        ]
        for add_dir in self._allowed_dirs(workdir):
            cmd.extend(["--add-dir", str(add_dir)])
        if include_partial_messages:
            cmd.append("--include-partial-messages")
        return cmd, env

    def _exec_cwd(self) -> Path:
        path = Path(os.environ.get("BRAIN_AGENT_PROXY_CLAUDE_EXEC_CWD", "/root"))
        if path.exists():
            return path
        return Path.cwd()

    def _normalize_model(self, model: str) -> str:
        value = str(model or "").strip()
        if "/" in value:
            _, _, value = value.partition("/")
        aliases = {
            "claude-sonnet-4.6": "claude-sonnet-4-6",
            "claude-opus-4.6": "claude-opus-4-6",
            "claude-haiku-4.5": "claude-haiku-4-5",
            "sonnet-4.6": "claude-sonnet-4-6",
            "opus-4.6": "claude-opus-4-6",
            "haiku-4.5": "claude-haiku-4-5",
        }
        return aliases.get(value, value or "claude-sonnet-4-6")

    def _base_system_prompt(self) -> str:
        return (
            "You are fulfilling one assistant turn for an upstream Anthropic-style conversation. "
            "Use the provided transcript and metadata to continue the turn. "
            "Use local Claude Code tools directly when needed. "
            "Do not mention the proxy wrapper or the existence of another upstream model. "
            "Return only the assistant's next reply."
        )

    def _build_prompt(self, request: Dict[str, Any]) -> str:
        lines = [
            "Conversation metadata follows.",
        ]
        upstream_system = _content_to_text(request.get("system", ""))
        if upstream_system.strip():
            lines.append("<system>")
            lines.append(upstream_system.strip())
            lines.append("</system>")

        tools = request.get("tools") or []
        if tools:
            lines.append("<tools>")
            lines.append(json.dumps(tools, ensure_ascii=False, indent=2))
            lines.append("</tools>")

        lines.extend([
            "Conversation transcript follows.",
            "Produce the next assistant turn.",
        ])
        for msg in request.get("messages", []) or []:
            role = str((msg or {}).get("role", "user") or "user")
            content = _content_to_text((msg or {}).get("content", ""))
            lines.append(f"<{role}>")
            lines.append(content.strip())
            lines.append(f"</{role}>")
        return "\n".join(lines).strip()

    def _resolve_workdir(self, request: Dict[str, Any]) -> Path:
        if self._workdir:
            path = Path(self._workdir)
            if path.exists():
                return path

        candidates: list[Path] = []
        for source in (request.get("system"), request.get("messages")):
            try:
                text = _content_to_text(source)
            except Exception:
                text = ""
            candidates.extend(_extract_paths(text))

        preferred_prefixes = [
            "/xkagent_infra/brain/agents",
            "/xkagent_infra/brain",
            "/root",
        ]
        for prefix in preferred_prefixes:
            for candidate in candidates:
                if str(candidate).startswith(prefix):
                    return candidate

        default_dir = os.environ.get("BRAIN_AGENT_PROXY_CLAUDE_DEFAULT_WORKDIR", "/xkagent_infra/brain")
        path = Path(default_dir)
        if path.exists():
            return path
        return Path.cwd()

    def _allowed_dirs(self, workdir: Path) -> list[Path]:
        defaults_raw = os.environ.get(
            "BRAIN_AGENT_PROXY_CLAUDE_DEFAULT_ADD_DIRS",
            "/root,/xkagent_infra/brain,/xkagent_infra/groups/brain/projects/base",
        )
        candidates: list[Path] = [workdir]
        for raw in defaults_raw.split(","):
            text = raw.strip()
            if not text:
                continue
            candidates.append(Path(text))

        out: list[Path] = []
        seen: set[str] = set()
        for path in candidates:
            try:
                resolved = str(path)
            except Exception:
                continue
            if not path.exists():
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            out.append(path)
        return out
