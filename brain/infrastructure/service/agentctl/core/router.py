from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from config.loader import YAMLConfigLoader


@dataclass(frozen=True)
class RouteDecision:
    target_agent: str
    reason: str
    matched_rule: str | None
    fallback_chain: list[str]


class Router:
    def __init__(self, loader: YAMLConfigLoader) -> None:
        self._loader = loader
        self._tag_index_cache: dict[str, list[str]] = {}
        self._tag_index_cache_time: float = 0
        self._tag_index_cache_ttl: float = 60.0  # 60 second TTL

    def route(self, message: str, user_ctx: dict[str, Any]) -> RouteDecision:
        routing = self._loader.get_routing_table().get("routing_table", {})
        defaults = routing.get("defaults", {}) or {}

        default_agent = str(defaults.get("default_agent") or "codex")
        no_match_behavior = str(defaults.get("no_match_behavior") or "fallback_to_default")

        agents_registry = self._safe_get_agents_registry()
        tag_index = self._build_tag_index(agents_registry)

        explicit = self._match_explicit_directive(
            message=message,
            routing=routing,
            tag_index=tag_index,
        )
        if explicit is not None:
            target_agent, matched_rule, reason = explicit
            return RouteDecision(
                target_agent=target_agent,
                reason=reason,
                matched_rule=matched_rule,
                fallback_chain=self._fallback_chain(routing, target_agent),
            )

        keyword = self._match_keywords(message=message, routing=routing)
        if keyword is not None:
            target_agent, matched_rule, reason = keyword
            return RouteDecision(
                target_agent=target_agent,
                reason=reason,
                matched_rule=matched_rule,
                fallback_chain=self._fallback_chain(routing, target_agent),
            )

        mapped = self._match_group_project_defaults(user_ctx=user_ctx, routing=routing)
        if mapped is not None:
            target_agent, matched_rule, reason = mapped
            return RouteDecision(
                target_agent=target_agent,
                reason=reason,
                matched_rule=matched_rule,
                fallback_chain=self._fallback_chain(routing, target_agent),
            )

        if no_match_behavior == "ask_clarify":
            return RouteDecision(
                target_agent=default_agent,
                reason="no_match_behavior=ask_clarify (fallback to default agent for clarification)",
                matched_rule=None,
                fallback_chain=self._fallback_chain(routing, default_agent),
            )

        return RouteDecision(
            target_agent=default_agent,
            reason="no_match (fallback_to_default)",
            matched_rule=None,
            fallback_chain=self._fallback_chain(routing, default_agent),
        )

    def _safe_get_agents_registry(self) -> dict[str, Any]:
        try:
            return self._loader.get_agents_registry()
        except Exception:
            return {}

    def _build_tag_index(self, agents_registry: dict[str, Any]) -> dict[str, list[str]]:
        # Check cache validity
        now = __import__('time').time()
        if now - self._tag_index_cache_time < self._tag_index_cache_ttl:
            return self._tag_index_cache
            
        tag_index: dict[str, list[str]] = {}
        agents = (agents_registry.get("agents_registry", {}) or {}).get("agents", []) or []
        if not isinstance(agents, list):
            self._tag_index_cache = tag_index
            self._tag_index_cache_time = now
            return tag_index

        for agent in agents:
            if not isinstance(agent, dict):
                continue
            name = str(agent.get("name") or "").strip()
            if not name:
                continue
            status = str(agent.get("status") or "active")
            if status not in ("active", "inactive", "planned"):
                status = "active"
            tags = agent.get("tags", []) or []
            if not isinstance(tags, list):
                continue
            for tag in tags:
                t = str(tag).strip()
                if not t:
                    continue
                tag_index.setdefault(t, [])
                if name not in tag_index[t]:
                    tag_index[t].append(name)
                    
        self._tag_index_cache = tag_index
        self._tag_index_cache_time = now
        return tag_index

    def _match_explicit_directive(
        self,
        message: str,
        routing: dict[str, Any],
        tag_index: dict[str, list[str]],
    ) -> tuple[str, str, str] | None:
        explicit = routing.get("explicit_directives", {}) or {}
        agent_prefix = str(explicit.get("agent_prefix") or "@")
        tag_prefix = str(explicit.get("tag_prefix") or "#")

        tokens = re.findall(r"[@#][^\\s]+", message)
        for token in tokens:
            if token.startswith(agent_prefix):
                val = token[len(agent_prefix) :].strip()
                if "/" in val:
                    group, project = val.split("/", 1)
                    group = group.strip()
                    project = project.strip()
                    if not group or not project:
                        continue
                    target = self._lookup_project_default(routing=routing, project_id=project)
                    if target is None:
                        target = self._lookup_group_default(routing=routing, group_id=group)
                    if target is not None:
                        return (
                            target,
                            f"explicit:project:{group}/{project}",
                            "explicit project directive",
                        )
                    continue
                if val:
                    return (val, f"explicit:agent:{val}", "explicit agent directive")

            if token.startswith(tag_prefix):
                tag = token.strip()
                agents = tag_index.get(tag, [])
                if agents:
                    return (agents[0], f"explicit:tag:{tag}", "explicit tag directive")

        return None

    def _match_keywords(self, message: str, routing: dict[str, Any]) -> tuple[str, str, str] | None:
        rules = routing.get("keyword_rules", []) or []
        if not isinstance(rules, list):
            return None

        best: tuple[int, str, str, str] | None = None  # (priority, target, matched_rule, reason)
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            match = rule.get("match", {}) or {}
            if not isinstance(match, dict):
                continue
            mtype = str(match.get("type") or "").strip()
            pattern = str(match.get("pattern") or "").strip()
            target = str(rule.get("target_agent") or "").strip()
            if not (mtype and pattern and target):
                continue

            try:
                priority = int(rule.get("priority", 0))
            except Exception:
                priority = 0

            matched = False
            if mtype == "keyword":
                matched = pattern in message
            elif mtype == "regex":
                matched = re.search(pattern, message) is not None
            else:
                continue

            if not matched:
                continue

            matched_rule = f"keyword:{mtype}:{pattern}"
            reason = "keyword rule matched"
            if best is None or priority > best[0]:
                best = (priority, target, matched_rule, reason)

        if best is None:
            return None
        _, target, matched_rule, reason = best
        return (target, matched_rule, reason)

    def _match_group_project_defaults(
        self, user_ctx: dict[str, Any], routing: dict[str, Any]
    ) -> tuple[str, str, str] | None:
        project_id = str(user_ctx.get("project_id") or "").strip()
        group_id = str(user_ctx.get("group_id") or "").strip()

        if project_id:
            target = self._lookup_project_default(routing=routing, project_id=project_id)
            if target is not None:
                return (target, f"project_default:{project_id}", "project default mapping")

        if group_id:
            target = self._lookup_group_default(routing=routing, group_id=group_id)
            if target is not None:
                return (target, f"group_default:{group_id}", "group default mapping")

        return None

    def _lookup_group_default(self, routing: dict[str, Any], group_id: str) -> str | None:
        groups = routing.get("group_defaults", []) or []
        if not isinstance(groups, list):
            return None
        for item in groups:
            if not isinstance(item, dict):
                continue
            if str(item.get("group_id") or "") == group_id:
                agent = str(item.get("default_agent") or "").strip()
                return agent or None
        return None

    def _lookup_project_default(self, routing: dict[str, Any], project_id: str) -> str | None:
        projects = routing.get("project_defaults", []) or []
        if not isinstance(projects, list):
            return None
        for item in projects:
            if not isinstance(item, dict):
                continue
            if str(item.get("project_id") or "") == project_id:
                agent = str(item.get("default_agent") or "").strip()
                return agent or None
        return None

    def _fallback_chain(self, routing: dict[str, Any], primary_agent: str) -> list[str]:
        chain: list[str] = []
        fallbacks = routing.get("fallbacks", []) or []
        if not isinstance(fallbacks, list):
            return chain
        for item in fallbacks:
            if not isinstance(item, dict):
                continue
            if str(item.get("primary_agent") or "") != primary_agent:
                continue
            agents = item.get("fallback_agents", []) or []
            if not isinstance(agents, list):
                continue
            for a in agents:
                s = str(a).strip()
                if s and s not in chain:
                    chain.append(s)
        return chain
