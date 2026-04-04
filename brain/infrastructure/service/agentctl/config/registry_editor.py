from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class RegistryEditError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentEntry:
    name: str
    tmux_session: str
    cwd: str
    # V1 fields (kept for backwards compat)
    start_cmd: str = ""
    desired_state: str = "running"
    required: bool = False
    status: str = "active"
    description: str = ""
    agent_name: str = ""
    tags: list[str] | None = None
    capabilities: list[str] | None = None
    # V2 fields
    role: str = ""
    scope: str = "group"
    group: str = ""
    project: str = ""
    sandbox_id: str = ""
    path: str = ""
    agent_type: str = "claude"
    agent_cli: str = ""  # claude/claude_code | native | "" (infer from agent_type)
    agent_model: str = "Sonnet"
    # legacy aliases (read-compat only; writer prefers agent_cli/agent_model)
    cli_type: str = ""
    model: str = ""
    transport_mode: str = ""
    effort: str = ""
    cli_args: list[str] | None = None
    env: dict[str, str] | None = None
    export_cmd: dict[str, str] | None = None
    initial_prompt: str = ""
    hooks: list[str] | None = None


def _indent(lines: list[str], spaces: int) -> list[str]:
    pad = " " * spaces
    return [pad + ln if ln else ln for ln in lines]


def _yaml_str(value: str) -> str:
    """Quote a string value for YAML output."""
    if not value:
        return '""'
    # Quote if contains special chars or looks like a YAML keyword
    needs_quote = any(c in value for c in ':#{}[]&*!|>\'"@%') or value.lower() in ("true", "false", "null", "~")
    if needs_quote:
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _group_key_for_line(stripped: str) -> str | None:
    """Return the group key for a `groups:` child line, if present."""
    if not stripped:
        return None
    indent = len(stripped) - len(stripped.lstrip())
    if indent != 2:
        return None
    body = stripped.strip()
    if body.startswith("-") or ":" not in body:
        return None
    return body.split(":", 1)[0].strip()


def render_agent_yaml_v2(entry: AgentEntry) -> str:
    """Render an AgentEntry in V2 groups format (2-space base indent)."""
    lines: list[str] = []
    lines.append(f"- name: {entry.name}")
    if entry.description:
        lines.append(f"  description: {_yaml_str(entry.description)}")
    if entry.role:
        lines.append(f"  role: {entry.role}")
    if entry.scope:
        lines.append(f"  scope: {entry.scope}")
    if entry.group:
        lines.append(f"  group: {entry.group}")
    if entry.project:
        lines.append(f"  project: {entry.project}")
    if entry.sandbox_id:
        lines.append(f"  sandbox_id: {entry.sandbox_id}")
    path = entry.path or entry.cwd
    if path:
        lines.append(f"  path: {path}")
    if entry.agent_type:
        lines.append(f"  agent_type: {entry.agent_type}")
    cli = entry.agent_cli or entry.cli_type
    model = entry.agent_model or entry.model
    if cli:
        lines.append(f"  agent_cli: {cli}")
    if model:
        lines.append(f"  agent_model: {model}")
    if entry.cli_type:
        lines.append(f"  cli_type: {entry.cli_type}")
    if entry.model:
        lines.append(f"  model: {entry.model}")
    if entry.transport_mode:
        lines.append(f"  transport_mode: {entry.transport_mode}")
    if entry.effort:
        lines.append(f"  effort: {entry.effort}")
    lines.append(f"  tmux_session: {entry.tmux_session}")
    if entry.cwd:
        lines.append(f"  cwd: {entry.cwd}")

    # cli_args
    if entry.cli_args:
        lines.append("  cli_args:")
        for arg in entry.cli_args:
            lines.append(f"    - {arg}")

    # env
    if entry.env:
        lines.append("  env:")
        for k, v in entry.env.items():
            lines.append(f"    {k}: {v}")

    # export_cmd
    if entry.export_cmd:
        lines.append("  export_cmd:")
        for k, v in entry.export_cmd.items():
            lines.append(f"    {k}: {v}")

    if entry.initial_prompt:
        lines.append(f"  initial_prompt: {entry.initial_prompt}")

    if entry.hooks:
        lines.append("  hooks:")
        for hook in entry.hooks:
            lines.append(f"    - {hook}")

    lines.append(f"  required: {str(bool(entry.required)).lower()}")
    lines.append(f"  desired_state: {entry.desired_state}")
    lines.append(f"  status: {entry.status}")

    if entry.capabilities:
        lines.append("  capabilities:")
        for c in entry.capabilities:
            lines.append(f"    - {c}")

    if entry.tags:
        lines.append("  tags:")
        for t in entry.tags:
            lines.append(f"    - '{t}'" if t.startswith("#") else f"    - {t}")

    return "\n".join(_indent(lines, 2)) + "\n"


# Legacy V1 renderer (kept for backwards compat)
def render_agent_yaml(entry: AgentEntry) -> str:
    lines: list[str] = []
    lines.append(f'- name: "{entry.name}"')
    if entry.description:
        lines.append(f'  description: "{entry.description}"')
    if entry.agent_name:
        lines.append(f'  agent_name: "{entry.agent_name}"')
    lines.append(f'  tmux_session: "{entry.tmux_session}"')
    lines.append(f'  cwd: "{entry.cwd}"')
    if entry.start_cmd:
        lines.append(f'  start_cmd: "{entry.start_cmd}"')
    lines.append(f"  required: {str(bool(entry.required)).lower()}")
    lines.append(f'  desired_state: "{entry.desired_state}"')
    if entry.capabilities:
        lines.append("  capabilities:")
        for c in entry.capabilities:
            lines.append(f'    - "{c}"')
    if entry.tags:
        lines.append("  tags:")
        for t in entry.tags:
            lines.append(f'    - "{t}"')
    lines.append(f'  status: "{entry.status}"')
    return "\n".join(_indent(lines, 4)) + "\n"


def append_agent_to_group(path: Path, group_name: str, entry: AgentEntry) -> None:
    """Append an agent entry under groups: -> {group_name}: in V2 registry format."""
    if not path.exists():
        raise RegistryEditError(f"agents_registry.yaml not found: {path}")
    text = path.read_text(encoding="utf-8")

    # Check agent doesn't already exist
    if f"name: {entry.name}" in text:
        raise RegistryEditError(f"agent already exists in registry: {entry.name}")

    lines = text.splitlines(keepends=True)

    # Find the groups: top-level key
    groups_idx = None
    for i, ln in enumerate(lines):
        stripped = ln.rstrip("\n\r")
        if stripped == "groups:" or stripped.startswith("groups:"):
            if not stripped[0].isspace():  # top-level key
                groups_idx = i
                break
    if groups_idx is None:
        raise RegistryEditError("could not find 'groups:' top-level key in agents_registry.yaml")

    # Find the target group header: "  {group_name}:"
    group_idx = None
    for i in range(groups_idx + 1, len(lines)):
        stripped = lines[i].rstrip("\n\r")
        # Stop if we hit another top-level key
        if stripped and not stripped[0].isspace() and ":" in stripped:
            break
        if _group_key_for_line(stripped) == group_name:
            group_idx = i
            suffix = stripped.strip().split(":", 1)[1].strip()
            if suffix == "[]":
                lines[i] = f"  {group_name}:\n"
            break

    block = render_agent_yaml_v2(entry)

    if group_idx is not None:
        # Group exists - find the last agent entry in this group
        # Agents are at indent 2 ("  - name: ..."), their fields at indent 4+
        insert_at = group_idx + 1
        for j in range(group_idx + 1, len(lines)):
            stripped = lines[j].rstrip("\n\r")
            if not stripped:
                insert_at = j + 1
                continue
            indent = len(stripped) - len(stripped.lstrip())
            if indent == 0 and ":" in stripped:
                insert_at = j
                break
            if _group_key_for_line(stripped) is not None:
                insert_at = j
                break
            insert_at = j + 1
        lines.insert(insert_at, block)
    else:
        # Group doesn't exist - find the end of groups section (before next top-level key)
        insert_at = len(lines)
        for j in range(groups_idx + 1, len(lines)):
            stripped = lines[j].rstrip("\n\r")
            if stripped and not stripped[0].isspace() and ":" in stripped:
                insert_at = j
                break

        # Insert new group key + agent block
        group_block = f"\n  {group_name}:\n{block}"
        lines.insert(insert_at, group_block)

    new_text = "".join(lines)
    if not new_text.endswith("\n"):
        new_text += "\n"
    path.write_text(new_text, encoding="utf-8")


def add_group_meta(path: Path, group_name: str, group_type: str, description: str) -> None:
    """Add a new group entry under group_meta: in the registry file."""
    if not path.exists():
        raise RegistryEditError(f"agents_registry.yaml not found: {path}")
    text = path.read_text(encoding="utf-8")

    # Check if group_meta already has this group
    if f"  {group_name}:" in text:
        # Could be under groups: or group_meta: - check specifically under group_meta
        lines = text.splitlines(keepends=True)
        in_group_meta = False
        for ln in lines:
            stripped = ln.rstrip("\n\r")
            if stripped == "group_meta:" or stripped.startswith("group_meta:"):
                if not stripped[0].isspace():
                    in_group_meta = True
                    continue
            if in_group_meta:
                if stripped and not stripped[0].isspace() and ":" in stripped:
                    in_group_meta = False
                    break
                if stripped.strip() == f"{group_name}:":
                    raise RegistryEditError(f"group_meta already contains: {group_name}")

    lines = text.splitlines(keepends=True)

    # Find group_meta: top-level key
    meta_idx = None
    for i, ln in enumerate(lines):
        stripped = ln.rstrip("\n\r")
        if stripped == "group_meta:" or stripped.startswith("group_meta:"):
            if not stripped[0].isspace():
                meta_idx = i
                break
    if meta_idx is None:
        raise RegistryEditError("could not find 'group_meta:' top-level key in agents_registry.yaml")

    # Find insertion point: before next top-level key after group_meta
    insert_at = len(lines)
    for j in range(meta_idx + 1, len(lines)):
        stripped = lines[j].rstrip("\n\r")
        if stripped and not stripped[0].isspace() and ":" in stripped:
            insert_at = j
            break

    meta_block = f"  {group_name}:\n    type: {group_type}\n    description: {_yaml_str(description)}\n"
    lines.insert(insert_at, meta_block)

    new_text = "".join(lines)
    if not new_text.endswith("\n"):
        new_text += "\n"
    path.write_text(new_text, encoding="utf-8")


# Legacy V1 function (kept for backwards compat)
def append_agent_to_registry_file(path: Path, entry: AgentEntry) -> None:
    if not path.exists():
        raise RegistryEditError(f"agents_registry.yaml not found: {path}")
    text = path.read_text(encoding="utf-8")

    if f'name: "{entry.name}"' in text or f"name: '{entry.name}'" in text or f"name: {entry.name}" in text:
        raise RegistryEditError(f"agent already exists in registry: {entry.name}")

    lines = text.splitlines(keepends=True)

    # Find the agents: list start
    agents_idx = None
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("agents:") and ln.startswith("  "):
            agents_idx = i
            break
    if agents_idx is None:
        raise RegistryEditError("could not find '  agents:' in agents_registry.yaml")

    # Find insertion point: before next top-level key at indent 2, after agents list.
    insert_at = None
    for j in range(agents_idx + 1, len(lines)):
        ln = lines[j]
        if not ln.strip():
            continue
        if ln.startswith("  ") and not ln.startswith("    ") and ":" in ln:
            insert_at = j
            break
    if insert_at is None:
        insert_at = len(lines)

    # Prefer inserting before any trailing comment block that precedes the next section key.
    k = insert_at
    while k > 0:
        prev = lines[k - 1]
        if prev.strip() == "":
            k -= 1
            continue
        if prev.startswith("  #"):
            k -= 1
            continue
        break
    insert_at = k

    block = render_agent_yaml(entry)
    if insert_at > 0 and lines[insert_at - 1].strip() != "":
        block = "\n" + block

    lines.insert(insert_at, block)
    new_text = "".join(lines)
    if not new_text.endswith("\n"):
        new_text += "\n"
    path.write_text(new_text, encoding="utf-8")


def get_registry_path(config_dir: Path) -> Path:
    return (config_dir / "agents_registry.yaml").resolve()
