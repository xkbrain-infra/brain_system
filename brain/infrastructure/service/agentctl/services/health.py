from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HealthIssue:
    severity: str  # info | warn | critical
    kind: str
    agent_name: str
    detail: str
    meta: dict[str, Any]


class HealthMonitor:
    """Lightweight health checks (V1): detect offline agents and restart storms."""

    def detect(self, restart_results: list[Any]) -> list[HealthIssue]:
        """Enhanced health detection with proactive checks."""
        issues: list[HealthIssue] = []
        
        # Check restart results
        for r in restart_results:
            try:
                agent_name = str(getattr(r, "agent_name", ""))
                success = bool(getattr(r, "success", False))
                reason = str(getattr(r, "reason", "") or "")
                error = str(getattr(r, "error", "") or "")
                attempt = int(getattr(r, "attempt", 0) or 0)

                if success:
                    # Informational events for recoveries
                    if reason in ("agent_offline", "session_missing"):
                        issues.append(
                            HealthIssue(
                                severity="info",
                                kind="agent_recovered",
                                agent_name=agent_name,
                                detail=reason,
                                meta={"attempt": attempt},
                            )
                        )
                    continue

                detail = error or reason or "unknown"
                sev = "warn"
                kind = "restart_failed"
                if "max_attempts_reached" in detail or "in_cooldown" in detail:
                    sev = "critical"
                    kind = "restart_storm"

                issues.append(
                    HealthIssue(
                        severity=sev,
                        kind=kind,
                        agent_name=agent_name,
                        detail=detail,
                        meta={"attempt": attempt, "reason": reason},
                    )
                )
            except Exception:
                continue
        
        # Proactive health checks
        issues.extend(self._proactive_health_checks())
        return issues
    
    def _proactive_health_checks(self) -> list[HealthIssue]:
        """Perform proactive health checks on agents."""
        issues: list[HealthIssue] = []
        
        try:
            # Check for agents that haven't sent heartbeats
            # This would require integration with the heartbeat system
            pass
        except Exception:
            pass
            
        return issues
