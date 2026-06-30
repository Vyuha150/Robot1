"""ConfidencePolicyManager — a single source of truth for "what SHOULD the
confidence thresholds be right now," across packages that currently set
them independently (gesture=0.65, face=0.55, voice=0.50, text=0.50 — found
during the efficiency audit, each in its own YAML with no coordination).

Honest limitation: this does NOT remotely reconfigure those packages — none
of them expose a live-reconfigure RPC. It publishes the recommended policy
(see PerceptionPolicy.msg) for operators/dashboards to read and for any
future package to subscribe to and apply. It also doesn't override a
package's MINIMUM safe threshold — recommendations are clamped to never go
below each signal's configured floor, so this can tighten precision under
degraded conditions but never silently make the system more permissive than
its own packages were built to allow.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConfidenceFloor:
    signal: str
    nominal_threshold: float
    minimum_threshold: float  # never recommend below this, regardless of mode


@dataclass
class PolicyRecommendation:
    signal: str
    recommended_threshold: float
    reason: str


_DEFAULT_FLOORS = [
    ConfidenceFloor("gesture", nominal_threshold=0.65, minimum_threshold=0.5),
    ConfidenceFloor("face", nominal_threshold=0.55, minimum_threshold=0.4),
    ConfidenceFloor("voice", nominal_threshold=0.50, minimum_threshold=0.35),
    ConfidenceFloor("text", nominal_threshold=0.50, minimum_threshold=0.35),
    ConfidenceFloor("object", nominal_threshold=0.50, minimum_threshold=0.3),
]


class ConfidencePolicyManager:
    def __init__(self, floors: list[ConfidenceFloor] | None = None) -> None:
        self._floors = {f.signal: f for f in (floors if floors else _DEFAULT_FLOORS)}

    def recommend(
        self, degraded: bool, safety_caution_or_above: bool
    ) -> list[PolicyRecommendation]:
        """Tighter (higher) thresholds when degraded or in a safety-elevated
        state, to reduce false-positive-driven behavior exactly when the
        system is least able to verify them — never looser than nominal."""
        out = []
        for signal, f in self._floors.items():
            threshold = f.nominal_threshold
            reason = "nominal"
            if degraded:
                threshold = min(1.0, f.nominal_threshold + 0.1)
                reason = "degraded mode — raised to reduce false positives"
            if safety_caution_or_above:
                threshold = max(threshold, min(1.0, f.nominal_threshold + 0.05))
                reason = "safety level elevated — raised to reduce false positives"
            threshold = max(threshold, f.minimum_threshold)
            out.append(PolicyRecommendation(signal, threshold, reason))
        return out

    def floor_for(self, signal: str) -> ConfidenceFloor | None:
        return self._floors.get(signal)
