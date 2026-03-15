"""Routing strategies."""
from abc import ABC, abstractmethod
from typing import List, Optional

from ..config import ProviderConfig


class RoutingStrategy(ABC):
    """Base class for routing strategies."""

    def __init__(self, providers: List[ProviderConfig]):
        self.providers = providers

    @abstractmethod
    def select(
        self,
        matching_providers: List[ProviderConfig],
        model: str,
    ) -> Optional[ProviderConfig]:
        """Select best provider from matching providers."""
        pass


class CapabilityMatchStrategy(RoutingStrategy):
    """Select provider based on capability match."""

    def select(
        self,
        matching_providers: List[ProviderConfig],
        model: str,
    ) -> Optional[ProviderConfig]:
        """Select provider with best capability match."""
        if not matching_providers:
            return None

        # Sort by priority (lower is better)
        matching_providers.sort(key=lambda p: p.priority)
        return matching_providers[0]


class CostWeightedStrategy(RoutingStrategy):
    """Select provider based on cost (prefer cheaper options)."""

    # Cost per 1M tokens (approximate)
    MODEL_COSTS = {
        "gpt-5-mini": 0.1,
        "gpt-4.1": 2.0,
        "gpt-4o": 5.0,
        "claude-sonnet-4.6": 3.0,
        "claude-opus-4": 15.0,
        "gemini-2.5-flash": 0.1,
        "gemini-2.5-pro": 1.25,
        "MiniMax-M2.5": 0.5,
    }

    def select(
        self,
        matching_providers: List[ProviderConfig],
        model: str,
    ) -> Optional[ProviderConfig]:
        """Select cheapest available provider."""
        if not matching_providers:
            return None

        # Get cost for model
        cost = self.MODEL_COSTS.get(model, 1.0)

        # Sort by priority (lower is better)
        matching_providers.sort(key=lambda p: p.priority)
        return matching_providers[0]


class AvailabilityStrategy(RoutingStrategy):
    """Select provider based on availability (first available)."""

    def select(
        self,
        matching_providers: List[ProviderConfig],
        model: str,
    ) -> Optional[ProviderConfig]:
        """Select first available provider."""
        if not matching_providers:
            return None

        # Sort by priority (lower is better)
        matching_providers.sort(key=lambda p: p.priority)
        return matching_providers[0]


class LatencyStrategy(RoutingStrategy):
    """Select provider based on latency (not implemented)."""

    def select(
        self,
        matching_providers: List[ProviderConfig],
        model: str,
    ) -> Optional[ProviderConfig]:
        """Select lowest latency provider."""
        # TODO: Implement latency-based selection
        if not matching_providers:
            return None
        matching_providers.sort(key=lambda p: p.priority)
        return matching_providers[0]
