from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except Exception as e:  # pragma: no cover
    yaml = None  # type: ignore
    _YAML_IMPORT_ERROR = e
else:
    _YAML_IMPORT_ERROR = None


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return line[:i]
    return line


def _parse_scalar(raw: str) -> Any:
    s = raw.strip()
    if s == "" or s == "~" or s.lower() == "null":
        return None
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        parts = [p.strip() for p in inner.split(",")]
        return [_parse_scalar(p) for p in parts]
    try:
        if "." in s:
            return float(s)
        return int(s)
    except Exception:
        return s


def _simple_yaml_load(text: str) -> Any:
    """Very small YAML subset loader.

    Supports:
      - mappings, nested by indentation (spaces)
      - sequences using "- "
      - scalars: str/bool/int/float/null and flow lists like [a, b]

    Not supported:
      - anchors, complex keys, multiline blocks, advanced flow styles
    """

    root: Any = {}
    stack: list[tuple[int, Any]] = [(-1, root)]

    def current_container() -> Any:
        return stack[-1][1]

    lines = text.splitlines()
    for idx, raw_line in enumerate(lines):
        line = _strip_comment(raw_line).rstrip("\n\r")
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip(" "))
        content = line.lstrip(" ")

        while stack and indent < stack[-1][0] and len(stack) > 1:
            stack.pop()

        container = current_container()

        if content.startswith("- "):
            item_str = content[2:].strip()
            if not isinstance(container, list):
                raise ConfigError("Invalid YAML: list item under non-list container")

            # Check if this looks like a mapping (contains ":" but not in a URL or quoted)
            # Look for ":" that's not inside quotes and not part of a URL
            colon_pos = -1
            in_single_quote = False
            in_double_quote = False
            for i, ch in enumerate(item_str):
                if ch == "'" and not in_double_quote:
                    in_single_quote = not in_single_quote
                elif ch == '"' and not in_single_quote:
                    in_double_quote = not in_double_quote
                elif ch == ":" and not in_single_quote and not in_double_quote:
                    # Check if this might be a URL (://)
                    if i + 2 < len(item_str) and item_str[i+1:i+3] == "//":
                        continue  # Skip URL colons
                    colon_pos = i
                    break

            if colon_pos > 0 and not item_str.startswith('"') and not item_str.startswith("'"):
                key = item_str[:colon_pos].strip()
                rest = item_str[colon_pos+1:].strip()
                item: dict[str, Any] = {}
                container.append(item)
                # Keys for this item continue at indent+2 in subsequent lines.
                stack.append((indent + 2, item))
                if rest == "":
                    next_container: Any = {}
                    # Lookahead: nested value might be a list.
                    for j in range(idx + 1, len(lines)):
                        nxt = _strip_comment(lines[j]).rstrip("\n\r")
                        if not nxt.strip():
                            continue
                        nxt_indent = len(nxt) - len(nxt.lstrip(" "))
                        if nxt_indent <= indent + 2:
                            break
                        nxt_content = nxt.lstrip(" ")
                        next_container = [] if nxt_content.startswith("- ") else {}
                        break
                    item[key] = next_container
                    stack.append((indent + 4, next_container))
                else:
                    item[key] = _parse_scalar(rest)
            else:
                container.append(_parse_scalar(item_str))
            continue

        if ":" not in content:
            raise ConfigError(f"Invalid YAML line (missing ':'): {raw_line}")

        key, rest = content.split(":", 1)
        key = key.strip()
        rest = rest.strip()

        if rest == "":
            # Lookahead to decide whether next container is a list or dict.
            next_container: Any = {}
            for j in range(idx + 1, len(lines)):
                nxt = _strip_comment(lines[j]).rstrip("\n\r")
                if not nxt.strip():
                    continue
                nxt_indent = len(nxt) - len(nxt.lstrip(" "))
                if nxt_indent <= indent:
                    break
                nxt_content = nxt.lstrip(" ")
                if nxt_content.startswith("- "):
                    next_container = []
                else:
                    next_container = {}
                break
            if isinstance(container, dict):
                container[key] = next_container
            else:
                raise ConfigError("Invalid YAML: mapping entry under non-dict container")
            stack.append((indent + 2, next_container))
        else:
            value = _parse_scalar(rest)
            if isinstance(container, dict):
                container[key] = value
            else:
                raise ConfigError("Invalid YAML: mapping entry under non-dict container")

    return root


DEFAULT_CONFIG_DIR = Path(
    os.environ.get(
        "AGENT_MANAGER_CONFIG_DIR",
        "/xkagent_infra/brain/infrastructure/config/agentctl",
    )
)


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class LoadedConfig:
    path: Path
    mtime_ns: int
    data: dict[str, Any]


class YAMLConfigLoader:
    """Loads YAML configs with mtime-based hot reload.

    V1 MUST:
      - routing_table.yaml hot reload

    Notes:
      - Uses a simple mtime_ns cache; call sites can call get_*() frequently.
      - yaml dependency is required at runtime (recommended via venv).
    """

    def __init__(self, config_dir: Path = DEFAULT_CONFIG_DIR) -> None:
        self._config_dir = config_dir
        self._lock = threading.Lock()
        self._cache: dict[str, LoadedConfig] = {}

    @property
    def config_dir(self) -> Path:
        return self._config_dir

    def _require_yaml(self) -> None:
        return

    def _load_yaml_file(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise ConfigError(f"Config not found: {path}")
        with path.open("r", encoding="utf-8") as f:
            text = f.read()
        if yaml is not None:
            data = yaml.safe_load(text)  # type: ignore[attr-defined]
        else:  # pragma: no cover
            data = _simple_yaml_load(text)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ConfigError(f"Config root must be a mapping: {path}")
        return data

    def _get(self, filename: str) -> LoadedConfig:
        path = (self._config_dir / filename).resolve()
        st = path.stat()
        mtime_ns = st.st_mtime_ns

        with self._lock:
            cached = self._cache.get(filename)
            if cached and cached.mtime_ns == mtime_ns and cached.path == path:
                return cached

            data = self._load_yaml_file(path)
            loaded = LoadedConfig(path=path, mtime_ns=mtime_ns, data=data)
            self._cache[filename] = loaded
            return loaded

    def force_reload(self, filename: str) -> LoadedConfig:
        with self._lock:
            self._cache.pop(filename, None)
        return self._get(filename)

    def reload(self) -> None:
        """Clear all cached configs with validation."""
        from config.validator import validate_agents_registry

        # Validate agents_registry.yaml before clearing cache
        try:
            agents_cfg = self.get_agents_registry()
            issues = validate_agents_registry(agents_cfg)
            errors = [i for i in issues if i.level == "error"]
            if errors:
                error_msgs = "; ".join([f"{e.agent or 'unknown'}: {e.message}" for e in errors])
                raise ConfigError(f"agents_registry.yaml validation failed: {error_msgs}")
        except Exception as e:
            # If validation fails, keep current cache and raise error
            raise ConfigError(f"Config reload validation failed: {e}")

        # Only clear cache if validation passed
        with self._lock:
            self._cache.clear()

    def get_routing_table(self) -> dict[str, Any]:
        return self._get("routing_table.yaml").data

    def get_agents_registry(self) -> dict[str, Any]:
        return self._get("agents_registry.yaml").data

    def get_whitelist(self) -> dict[str, Any]:
        return self._get("whitelist.yaml").data
