"""FrameSamplingManager — central, coordinated frame-sample-rate recommendations.

bonbon_vision has its own frame throttler; bonbon_gesture has its own
frame_sample_rate parameter. Both are independently configured with no
awareness of each other or of current system load. This does not replace
either — it computes a RECOMMENDED sample-every-Nth-frame value per consumer
based on current load, and publishes it (see PerceptionBudget.msg) for any
node that chooses to read it.

Honest limitation: no node currently has a live-reconfigure path to actually
APPLY this recommendation automatically — wiring gesture_node/vision_node to
subscribe and apply it is a Phase 4 runtime-optimization follow-up, not
something this module can force from the outside. This is advisory
coordination, consistent with the project's "advise, never command" pattern
for any module that isn't the Safety Supervisor.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SampleRateRecommendation:
    consumer: str
    sample_every_n_frames: int
    reason: str


class FrameSamplingManager:
    def __init__(self, base_rates: dict[str, int] | None = None) -> None:
        # Sensible defaults matching each package's own existing baseline,
        # so a fresh recommendation under nominal load matches what the
        # consumer is already doing (no surprise behavior change at rest).
        self._base_rates = base_rates or {"vision": 1, "gesture": 3}

    def recommend(self, load_shed_scale: float) -> list[SampleRateRecommendation]:
        """load_shed_scale: (0.0, 1.0], 1.0 = full rate (from ResourceMonitor/
        LoadSheddingController). Lower scale -> larger N (sample less often)."""
        scale = max(0.1, min(1.0, load_shed_scale))
        out = []
        for consumer, base_n in self._base_rates.items():
            # Inflate N inversely with scale: at scale=1.0, N unchanged;
            # at scale=0.5, N roughly doubles (sample half as often).
            recommended_n = max(base_n, round(base_n / scale))
            reason = "nominal load" if scale >= 0.99 else f"load shed scale={scale:.2f}"
            out.append(SampleRateRecommendation(consumer, recommended_n, reason))
        return out
