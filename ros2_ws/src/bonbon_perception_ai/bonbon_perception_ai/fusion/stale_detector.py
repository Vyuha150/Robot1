"""
bonbon_perception_ai.fusion.stale_detector
===========================================
Assesses which modalities are stale and derives an overall uncertainty level.

Design rule
-----------
* 0 stale modalities        → UNCERTAINTY_LOW
* 1–2 stale modalities      → UNCERTAINTY_MEDIUM
* 3 or more stale           → UNCERTAINTY_HIGH

The thresholds are intentionally generous: a robot should still be able to act
on fresh vision data even if the nav-state topic is momentarily quiet.
"""

from __future__ import annotations

from bonbon_perception_ai.fusion.modality_buffer import ModalityBuffer

# ── Uncertainty constants (match SemanticScene.msg) ──────────────────────────
UNCERTAINTY_LOW = "LOW"
UNCERTAINTY_MEDIUM = "MEDIUM"
UNCERTAINTY_HIGH = "HIGH"

_STALE_TO_UNCERTAINTY: dict[int, str] = {
    0: UNCERTAINTY_LOW,
    1: UNCERTAINTY_MEDIUM,
    2: UNCERTAINTY_MEDIUM,
}


class StaleDetector:
    """
    Stateless utility that inspects a dict of ModalityBuffers and returns
    (stale_names, uncertainty_level).
    """

    def assess(self, buffers: dict[str, ModalityBuffer]) -> tuple[list[str], str]:
        """
        Parameters
        ----------
        buffers :
            Mapping of modality name → ModalityBuffer.

        Returns
        -------
        stale_modalities :
            Names of modalities whose last update is older than their timeout.
        uncertainty_level :
            "LOW" | "MEDIUM" | "HIGH"
        """
        stale = [name for name, buf in buffers.items() if buf.is_stale()]
        uncertainty = _STALE_TO_UNCERTAINTY.get(len(stale), UNCERTAINTY_HIGH)
        return stale, uncertainty

    def detail_report(self, buffers: dict[str, ModalityBuffer]) -> dict[str, float]:
        """
        Return per-modality age in seconds.
        Useful for health reporting and debug logs.
        """
        return {name: buf.age_sec() for name, buf in buffers.items()}
