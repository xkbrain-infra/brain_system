#!/usr/bin/env python3
"""
LEP Engine (shared runtime module)

Purpose:
- Load /brain/base/spec/core/lep.yaml
- Provide matching helpers for gates.applies_to

Supports semantic applies_to wildcards:
- applies_to: all
- applies_to: "*"
- applies_to: ["*"]
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import os

import yaml


LEP_FILE_DEFAULT = "/brain/base/spec/core/lep.yaml"
LEP_FILE_LOCAL = "/brain/.claude/lep.yaml"


def _hook_root() -> Path | None:
    hook_root = os.environ.get("HOOK_ROOT", "").strip()
    if not hook_root:
        return None
    try:
        return Path(hook_root).resolve()
    except Exception:
        return Path(hook_root)


def _hook_relative_lep_path() -> str | None:
    hook_root = _hook_root()
    if hook_root is None:
        return None
    candidate = (hook_root.parent / "spec" / "core" / "lep.yaml").resolve()
    if candidate.exists():
        return str(candidate)
    return None


@dataclass(frozen=True)
class LepConfig:
    actions: dict[str, list[str]]
    gates: dict[str, dict[str, Any]]
    command_mapping: dict[str, Any] | None = None


def get_lep_path() -> str:
    """Get LEP file path with local override support

    Priority:
        1. Local agent config: /brain/.claude/lep.yaml
        2. Global config: /brain/base/spec/core/lep.yaml

    Returns:
        str: Path to LEP config file
    """
    # Check local config first (agent-specific rules)
    if os.path.exists(LEP_FILE_LOCAL):
        return LEP_FILE_LOCAL

    hook_relative = _hook_relative_lep_path()
    if hook_relative:
        return hook_relative

    # Fall back to global config
    return LEP_FILE_DEFAULT


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load YAML file safely, returning empty dict on failure."""
    try:
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _resolve_spec_root(lep_path: str) -> Path:
    """
    Resolve /brain/base/spec root for legacy core lep.yaml.

    Example:
      /brain/base/spec/core/lep.yaml -> /brain/base/spec
    """
    p = Path(lep_path).resolve()
    if p.parent.name == "core":
        return p.parent.parent
    return p.parent


def _build_legacy_gates(data: dict[str, Any], lep_path: str) -> dict[str, dict[str, Any]]:
    """
    Backward-compat:
    core/lep.yaml historically stores gate ids in:
      - universal_gates
      - domain_gates_summary
    while enforcement details live in policies/lep/*.yaml.

    This function materializes runtime gates map used by LepEngine.
    """
    gates: dict[str, dict[str, Any]] = {}
    spec_root = _resolve_spec_root(lep_path)

    # Build id -> filename map from policies index (if available)
    idx_path = spec_root / "policies" / "lep" / "index.yaml"
    idx = _load_yaml(idx_path)
    gate_file_map: dict[str, str] = {}
    for item in idx.get("gates", []):
        gid = item.get("id")
        fname = item.get("file")
        if isinstance(gid, str) and isinstance(fname, str):
            gate_file_map[gid] = fname

    def load_gate_policy(gate_id: str, detail_rel: str | None = None) -> dict[str, Any]:
        candidates: list[Path] = []
        if detail_rel:
            candidates.append(spec_root / detail_rel)
        fname = gate_file_map.get(gate_id)
        if fname:
            candidates.append(spec_root / "policies" / "lep" / fname)

        for c in candidates:
            cfg = _load_yaml(c)
            if cfg:
                return cfg
        return {}

    # 1) universal gates (includes detail path in core/lep.yaml)
    for gate_id, gate_meta in (data.get("universal_gates") or {}).items():
        if not isinstance(gate_id, str) or not isinstance(gate_meta, dict):
            continue

        policy = load_gate_policy(gate_id, gate_meta.get("detail"))
        if not policy:
            # Fallback: keep minimal metadata so gate is visible
            policy = dict(gate_meta)
        else:
            # Merge core metadata into policy when absent
            for k in ("name", "applies_to", "rule", "priority"):
                if k not in policy and k in gate_meta:
                    policy[k] = gate_meta[k]

        gates[gate_id] = policy

    # 2) domain summary gates (resolve via index -> policy file)
    for gate_ids in (data.get("domain_gates_summary") or {}).values():
        if not isinstance(gate_ids, list):
            continue
        for gate_id in gate_ids:
            if not isinstance(gate_id, str) or gate_id in gates:
                continue
            policy = load_gate_policy(gate_id)
            if policy:
                gates[gate_id] = policy

    return gates


def load_lep(path: str = None) -> LepConfig:
    """Load LEP config from file

    Args:
        path: Optional path to LEP file. If None, uses get_lep_path()

    Returns:
        LepConfig: Loaded configuration
    """
    if path is None:
        path = get_lep_path()
    if not os.path.exists(path):
        return LepConfig(actions={}, gates={}, command_mapping=None)
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    actions = data.get("actions") or {}
    gates = data.get("gates") or {}

    # Backward compatibility:
    # If no runtime gates map exists, derive it from legacy core format.
    if not gates and (data.get("universal_gates") or data.get("domain_gates_summary")):
        gates = _build_legacy_gates(data, path)

    command_mapping = data.get("command_mapping")
    return LepConfig(actions=actions, gates=gates, command_mapping=command_mapping)


def _is_all_token(token: str) -> bool:
    t = token.strip().lower()
    return t in {"*", "all"}


def expand_applies_to(applies_to: Any, all_actions: Iterable[str]) -> list[str]:
    """
    Normalizes a gate's applies_to into a list of action names.

    Accepts:
    - list[str]
    - str
    - None

    Wildcards:
    - "all" / "*" expands to all_actions.
    """
    all_actions_list = list(all_actions)

    if applies_to is None:
        return []

    if isinstance(applies_to, str):
        return all_actions_list if _is_all_token(applies_to) else [applies_to]

    if isinstance(applies_to, list):
        tokens: list[str] = []
        for item in applies_to:
            if item is None:
                continue
            if not isinstance(item, str):
                tokens.append(str(item))
                continue
            if _is_all_token(item):
                return all_actions_list
            tokens.append(item)
        return tokens

    s = str(applies_to)
    return all_actions_list if _is_all_token(s) else [s]


def gate_applies(gate: dict[str, Any], action: str, all_actions: Iterable[str]) -> bool:
    applies_to = expand_applies_to(gate.get("applies_to"), all_actions=all_actions)
    return action in set(applies_to)


__all__ = ["LepConfig", "LEP_FILE_DEFAULT", "LEP_FILE_LOCAL", "get_lep_path", "load_lep", "expand_applies_to", "gate_applies"]
