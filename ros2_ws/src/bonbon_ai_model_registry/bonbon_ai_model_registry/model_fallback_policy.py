"""FallbackPolicy — turns a capability's registered fallback chain
(ModelRegistry.fallback_chain) plus a set of availability results into
one decision: which model is ACTIVE right now, and is a fallback active.
Kept separate from model_runtime_selector.py because the policy question
("given these availabilities, which one wins") is pure and easy to test
in isolation from the availability-checking side effects (imports,
subprocess calls, network probes) runtime_selector performs.
"""

from __future__ import annotations

from dataclasses import dataclass

from bonbon_ai_model_registry.model_registry import ModelEntry, ModelRegistry


@dataclass
class FallbackDecision:
    capability: str
    requested_model_id: str
    active_model_id: str | None
    fallback_active: bool
    degraded: bool
    reason: str
    chain_tried: list[str]


class FallbackPolicy:
    def __init__(self, registry: ModelRegistry) -> None:
        self._registry = registry

    def resolve(
        self,
        capability: str,
        availability: dict[str, bool],
        *,
        preferred_model_id: str | None = None,
    ) -> FallbackDecision:
        """`availability` maps model_id -> is it actually usable right now
        (already-computed by model_runtime_selector, never guessed here).
        Walks preferred_model_id's fallback chain (or the capability's
        registered default if none given) until one is available.
        Returns degraded=True with active_model_id=None if the entire
        chain is exhausted -- callers must handle that as a real
        "capability unavailable" state, never silently pretend the first
        entry worked."""
        start = self._registry.get(preferred_model_id) if preferred_model_id else self._registry.default_for_capability(capability)
        if start is None:
            return FallbackDecision(capability, preferred_model_id or "", None, False, True, f"no registered default for capability {capability!r}", [])

        chain = self._registry.fallback_chain(start.model_id)
        tried: list[str] = []
        for entry in chain:
            tried.append(entry.model_id)
            if availability.get(entry.model_id, False):
                fallback_active = entry.model_id != start.model_id
                reason = "primary model available" if not fallback_active else f"fell back from {start.model_id!r} to {entry.model_id!r}"
                return FallbackDecision(capability, start.model_id, entry.model_id, fallback_active, False, reason, tried)

        return FallbackDecision(
            capability, start.model_id, None, True, True,
            f"entire fallback chain exhausted ({' -> '.join(tried)}) -- capability is genuinely unavailable, not silently degraded to a fake pass",
            tried,
        )

    def chain_for_dashboard(self, capability: str) -> list[dict]:
        """Read-only view of the configured chain (not availability) for
        a dashboard to render even before any health check has run."""
        default = self._registry.default_for_capability(capability)
        if default is None:
            return []
        return [
            {"modelId": e.model_id, "provider": e.provider, "modelName": e.model_name}
            for e in self._registry.fallback_chain(default.model_id)
        ]
