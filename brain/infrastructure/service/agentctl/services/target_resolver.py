from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config.loader import YAMLConfigLoader


class TargetResolutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class TargetResolution:
    requested: str
    resolved: str
    strategy: str  # passthrough | unique_online | preferred_session | offline_passthrough
    candidates: list[str]


class AmbiguousTarget(TargetResolutionError):
    def __init__(self, requested: str, candidates: list[str]) -> None:
        super().__init__(f"ambiguous target agent_name='{requested}' (multiple online instances)")
        self.requested = requested
        self.candidates = candidates


class TargetResolver:
    """Resolve logical agent names into daemon instance_id.

    Rules:
      - If input looks like instance_id (contains '@'), return as-is.
      - If exactly one online instance exists for agent_name, use it.
      - If multiple online instances exist, try select one by preferred tmux_session:
          - explicit preferred_tmux_session parameter, else
          - agents_registry.yaml tmux_session for that agent name
        If still ambiguous, raise AmbiguousTarget with candidates.
      - If no online instances exist, return logical name as-is (daemon can offline-queue).
    """

    def __init__(self, daemon: Any, config_loader: YAMLConfigLoader | None = None) -> None:
        self._daemon = daemon
        self._config_loader = config_loader

    def resolve(
        self, target: str, preferred_tmux_session: str | None = None
    ) -> TargetResolution:
        raw = (target or "").strip()
        if not raw:
            raise TargetResolutionError("empty target")

        if "@" in raw:
            return TargetResolution(
                requested=raw,
                resolved=raw,
                strategy="passthrough",
                candidates=[],
            )

        # Allow logical target names that map to an underlying daemon agent_name via registry.
        mapped_agent_name, mapped_session = self._map_logical_target(raw)
        runtime_agent_name = mapped_agent_name or raw
        preferred_session = preferred_tmux_session or mapped_session

        instances = self._list_online_instances(agent_name=runtime_agent_name)
        candidates = [i.get("instance_id", "") for i in instances if i.get("instance_id")]
        if len(candidates) == 1:
            return TargetResolution(
                requested=raw,
                resolved=candidates[0],
                strategy="unique_online",
                candidates=candidates,
            )

        if len(candidates) > 1:
            preferred = preferred_session or self._preferred_session_from_registry(runtime_agent_name)
            if preferred:
                for inst in instances:
                    if str(inst.get("tmux_session") or "") == preferred:
                        iid = str(inst.get("instance_id") or "").strip()
                        if iid:
                            return TargetResolution(
                                requested=raw,
                                resolved=iid,
                                strategy="preferred_session",
                                candidates=candidates,
                            )
            raise AmbiguousTarget(raw, candidates)

        return TargetResolution(
            requested=raw,
            resolved=runtime_agent_name if runtime_agent_name else raw,
            strategy="offline_passthrough",
            candidates=[],
        )

    def _map_logical_target(self, target: str) -> tuple[str | None, str | None]:
        """Map a logical target name to (agent_name, tmux_session) based on agents_registry.yaml.

        This enables provisioning multiple tmux sessions (instances) under one daemon agent_name
        (e.g. claude@session:*), while routing via a stable logical name.
        """
        if self._config_loader is None:
            return None, None
        try:
            cfg = self._config_loader.get_agents_registry()
            root = cfg.get("agents_registry", {}) if isinstance(cfg, dict) else {}
            agents = root.get("agents", []) if isinstance(root, dict) else []
            if not isinstance(agents, list):
                return None, None
            for a in agents:
                if not isinstance(a, dict):
                    continue
                if str(a.get("name") or "").strip() != target:
                    continue
                agent_name = str(a.get("agent_name") or "").strip() or None
                tmux_session = str(a.get("tmux_session") or "").strip() or None
                return agent_name, tmux_session
        except Exception:
            return None, None
        return None, None

    def _preferred_session_from_registry(self, agent_name: str) -> str | None:
        if self._config_loader is None:
            return None
        try:
            cfg = self._config_loader.get_agents_registry()
            root = cfg.get("agents_registry", {}) if isinstance(cfg, dict) else {}
            agents = root.get("agents", []) if isinstance(root, dict) else []
            if not isinstance(agents, list):
                return None
            for a in agents:
                if not isinstance(a, dict):
                    continue
                if str(a.get("name") or "") == agent_name:
                    s = str(a.get("tmux_session") or "").strip()
                    return s or None
        except Exception:
            return None
        return None

    def _list_online_instances(self, agent_name: str) -> list[dict[str, Any]]:
        resp = self._daemon.list_agents(include_offline=False)
        if not isinstance(resp, dict) or resp.get("status") != "ok":
            return []
        instances = resp.get("instances", []) or []
        if not isinstance(instances, list):
            return []
        out: list[dict[str, Any]] = []
        for inst in instances:
            if not isinstance(inst, dict):
                continue
            if str(inst.get("agent_name") or "") != agent_name:
                continue
            if not bool(inst.get("online")):
                continue
            out.append(inst)
        return out
