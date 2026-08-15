"""Detects genuinely conflicting emotion signals so fusion can report 'uncertain'
instead of overclaiming confidence in one of the other 11 dominant states.

See docs/MULTI_HUMAN_EMOTION_FAILURE_ANALYSIS.md's Phase 4 fix scope: "uncertain"
was never emitted anywhere, so a person with genuinely mixed signals (e.g. a
neutral face but a distressed voice) was always forced into one of the 10-11
other states with unwarranted confidence.
"""

from __future__ import annotations

from typing import Dict


class EmotionUncertaintyHandler:
    """Flags a fused result as 'uncertain' when two or more modalities
    genuinely disagree on the dominant state, rather than one modality
    simply being unavailable or low-confidence.

    A single modality voting alone (or all modalities agreeing) is never
    "conflicting" -- conflict requires at least two competing states with
    comparably-weighted support.
    """

    def __init__(self, conflict_margin: float = 0.75, min_second_weight: float = 0.05) -> None:
        """Initialise the handler.

        Args:
            conflict_margin: The second-highest state's total vote weight
                must be at least this fraction of the highest state's
                weight to count as a genuine conflict (0-1). Higher means
                stricter (only near-ties count as uncertain).
            min_second_weight: The second-highest state must also carry at
                least this much absolute weight, so a near-zero stray vote
                (e.g. a low-confidence gesture) never triggers "uncertain"
                on its own.
        """
        self._conflict_margin = conflict_margin
        self._min_second_weight = min_second_weight

    def is_conflicting(self, state_votes: Dict[str, float]) -> bool:
        """Determine whether the aggregated per-state votes represent a
        genuine, unresolved conflict between modalities.

        Args:
            state_votes: Mapping of candidate state label to total weighted
                vote (as built by ``EmotionFusionEngine._compute_weighted_state``).

        Returns:
            bool: True if two or more states have comparably strong,
                independently-contributed support -- the fused result should
                be reported as "uncertain" rather than committing to either.
        """
        if len(state_votes) < 2:
            return False

        ranked = sorted(state_votes.values(), reverse=True)
        top, second = ranked[0], ranked[1]

        if top <= 0.0 or second < self._min_second_weight:
            return False

        return (second / top) >= self._conflict_margin
