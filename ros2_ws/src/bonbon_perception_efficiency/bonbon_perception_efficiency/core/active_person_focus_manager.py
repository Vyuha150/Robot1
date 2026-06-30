"""ActivePersonFocusManager — the genuinely new capability from the efficiency
audit: nothing in the codebase reduces processing for background people.

bonbon_behavior_engine's select_focus_person (built earlier) decides who the
robot TALKS to — a behavioral decision. This is a different question: given
the current focus person, how much processing budget should EACH tracked
person's gesture/face/voice pipeline get? A focus person should be processed
at full rate; people who are merely present in the background can be
processed at a reduced rate to free up budget.

This does not perform any processing itself, and does not change who the
robot interacts with — it only computes a recommended per-person weight,
published as part of PerceptionBudget.msg, for perception nodes to use when
deciding (for instance) which person's gesture landmarks to run through the
backend first, or how often to re-run face recognition on a background
person already confidently identified.

bonbon_human_state_fusion's FocusPublishGate is the first real consumer:
it reduces HumanState publish cadence for background people specifically
(see that package's core/focus_publish_gate.py).
"""

from __future__ import annotations

from dataclasses import dataclass

FULL_FOCUS_WEIGHT = 1.0
BACKGROUND_WEIGHT = 0.3
NEW_ARRIVAL_WEIGHT = 0.8  # briefly prioritised so arrival behaviors aren't missed


@dataclass
class PersonFocusWeight:
    person_track_id: str
    weight: float
    reason: str


class ActivePersonFocusManager:
    def compute_weights(
        self, focus_person_track_id: str, person_track_ids: list[str], new_candidate_ids: set[str]
    ) -> list[PersonFocusWeight]:
        out = []
        for pid in person_track_ids:
            if pid == focus_person_track_id and pid:
                out.append(PersonFocusWeight(pid, FULL_FOCUS_WEIGHT, "active focus"))
            elif pid in new_candidate_ids:
                out.append(
                    PersonFocusWeight(pid, NEW_ARRIVAL_WEIGHT, "newly arrived — brief priority")
                )
            else:
                out.append(PersonFocusWeight(pid, BACKGROUND_WEIGHT, "background"))
        return out
