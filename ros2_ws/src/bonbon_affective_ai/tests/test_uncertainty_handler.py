"""Tests for EmotionUncertaintyHandler -- conflicting-signal detection."""

from __future__ import annotations

import unittest

from bonbon_affective_ai.fusion.uncertainty_handler import EmotionUncertaintyHandler


class TestEmotionUncertaintyHandler(unittest.TestCase):
    """Tests for EmotionUncertaintyHandler.is_conflicting."""

    def setUp(self) -> None:
        self.handler = EmotionUncertaintyHandler(conflict_margin=0.75, min_second_weight=0.05)

    def test_single_state_is_never_conflicting(self) -> None:
        """Every modality agreeing on one state is never a conflict."""
        self.assertFalse(self.handler.is_conflicting({"happy": 0.7}))

    def test_empty_votes_is_never_conflicting(self) -> None:
        """No modality voting at all is never a conflict."""
        self.assertFalse(self.handler.is_conflicting({}))

    def test_near_tie_between_two_states_is_conflicting(self) -> None:
        """A close second (>=75% of the top) is a genuine conflict."""
        self.assertTrue(self.handler.is_conflicting({"happy": 0.28, "distressed": 0.2625}))

    def test_clear_winner_is_not_conflicting(self) -> None:
        """A dominant top state with a weak second is not a conflict."""
        self.assertFalse(self.handler.is_conflicting({"angry": 0.7, "neutral": 0.05}))

    def test_tiny_second_vote_is_not_conflicting(self) -> None:
        """A near-zero stray vote (e.g. a low-confidence gesture) never
        triggers uncertainty on its own, even if its ratio would qualify."""
        self.assertFalse(self.handler.is_conflicting({"happy": 0.02, "neutral": 0.018}))

    def test_three_way_conflict_is_conflicting(self) -> None:
        """Three competing states with the top two close together still
        counts as a conflict (only the top two matter)."""
        self.assertTrue(
            self.handler.is_conflicting({"happy": 0.30, "distressed": 0.29, "confused": 0.05})
        )

    def test_stricter_margin_rejects_a_moderate_gap(self) -> None:
        """A higher conflict_margin requires a closer near-tie."""
        strict_handler = EmotionUncertaintyHandler(conflict_margin=0.95, min_second_weight=0.05)
        self.assertFalse(strict_handler.is_conflicting({"happy": 0.30, "distressed": 0.25}))


if __name__ == "__main__":
    unittest.main()
