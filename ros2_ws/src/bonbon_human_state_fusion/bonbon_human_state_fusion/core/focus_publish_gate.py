"""FocusPublishGate — decides which per-person HumanState updates to
actually publish this cycle, based on bonbon_perception_efficiency's
ActivePersonFocusManager per-person weight.

This is THE real consumer that makes active-person focus genuinely reduce
processing for background people. ActivePersonFocusManager itself only
recommends a weight (advisory, see its own README "honest limitations");
nothing previously read that weight to change any node's actual behavior.
human_state_fusion_node is the natural place to apply it: it already
iterates every tracked person every cycle to build HumanState, and
reducing PUBLISH frequency for background people genuinely reduces
downstream processing/bandwidth — the same "reduce rate, don't redo
detection" pattern bonbon_perception_efficiency's FrameSamplingManager
already uses for bonbon_vision.

Reuses select_focus_person (bonbon_behavior_engine) and
ActivePersonFocusManager (bonbon_perception_efficiency) directly rather
than re-deriving either's priority logic a third time.

Always published, never throttled:
  - LEFT_SCENE results (terminal, one-time — must never be silently
    dropped just because that person was previously in the background).
  - The current focus person (weight 1.0) and new arrivals (weight 0.8,
    brief priority).
Background people (weight 0.3) publish only once every
background_publish_every_n_cycles.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bonbon_behavior_engine.core.multi_person_behavior_selector import select_focus_person
from bonbon_perception_efficiency.core.active_person_focus_manager import (
    BACKGROUND_WEIGHT,
    ActivePersonFocusManager,
)

_LEFT_SCENE = "left_scene"
_NEW_CANDIDATE = "new_candidate"


@dataclass
class FocusPublishDecision:
    to_publish: list = field(default_factory=list)
    focus_person_track_id: str = ""


class FocusPublishGate:
    def __init__(
        self,
        background_publish_every_n_cycles: int = 3,
        focus_manager: ActivePersonFocusManager | None = None,
    ) -> None:
        self._n = max(1, background_publish_every_n_cycles)
        self._focus_manager = focus_manager or ActivePersonFocusManager()
        self._cycle_count: dict[str, int] = {}

    def select(self, results: list) -> FocusPublishDecision:
        focus_id = select_focus_person(results) if results else ""
        present_ids = [r.person_track_id for r in results if r.lifecycle_state != _LEFT_SCENE]
        new_candidate_ids = {
            r.person_track_id for r in results if r.lifecycle_state == _NEW_CANDIDATE
        }
        weights = {
            w.person_track_id: w.weight
            for w in self._focus_manager.compute_weights(focus_id, present_ids, new_candidate_ids)
        }

        to_publish = []
        seen_ids = set()
        for r in results:
            seen_ids.add(r.person_track_id)

            if r.lifecycle_state == _LEFT_SCENE:
                to_publish.append(r)
                continue

            weight = weights.get(r.person_track_id, 1.0)
            if weight > BACKGROUND_WEIGHT:
                to_publish.append(r)
                self._cycle_count.pop(r.person_track_id, None)
                continue

            count = self._cycle_count.get(r.person_track_id, 0) + 1
            if count >= self._n:
                to_publish.append(r)
                count = 0
            self._cycle_count[r.person_track_id] = count

        # Prune throttle counters for anyone no longer in this cycle's
        # results at all, so the dict doesn't grow without bound.
        for pid in list(self._cycle_count.keys()):
            if pid not in seen_ids:
                self._cycle_count.pop(pid, None)

        return FocusPublishDecision(to_publish=to_publish, focus_person_track_id=focus_id)
