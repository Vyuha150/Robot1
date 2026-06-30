"""Tests for ActivePersonFocusManager."""

from __future__ import annotations

from bonbon_perception_efficiency.core.active_person_focus_manager import (
    BACKGROUND_WEIGHT,
    FULL_FOCUS_WEIGHT,
    NEW_ARRIVAL_WEIGHT,
    ActivePersonFocusManager,
)


class TestFocusWeighting:
    def test_focus_person_gets_full_weight(self):
        mgr = ActivePersonFocusManager()
        weights = mgr.compute_weights("ptrk_1", ["ptrk_1", "ptrk_2"], set())
        focus = next(w for w in weights if w.person_track_id == "ptrk_1")
        assert focus.weight == FULL_FOCUS_WEIGHT

    def test_background_person_gets_reduced_weight(self):
        mgr = ActivePersonFocusManager()
        weights = mgr.compute_weights("ptrk_1", ["ptrk_1", "ptrk_2"], set())
        bg = next(w for w in weights if w.person_track_id == "ptrk_2")
        assert bg.weight == BACKGROUND_WEIGHT
        assert bg.weight < FULL_FOCUS_WEIGHT

    def test_new_arrival_gets_brief_priority_over_background(self):
        mgr = ActivePersonFocusManager()
        weights = mgr.compute_weights("ptrk_1", ["ptrk_1", "ptrk_2"], {"ptrk_2"})
        arrival = next(w for w in weights if w.person_track_id == "ptrk_2")
        assert arrival.weight == NEW_ARRIVAL_WEIGHT
        assert BACKGROUND_WEIGHT < arrival.weight < FULL_FOCUS_WEIGHT

    def test_no_focus_person_everyone_gets_background_or_arrival_weight(self):
        mgr = ActivePersonFocusManager()
        weights = mgr.compute_weights("", ["ptrk_1", "ptrk_2"], set())
        assert all(w.weight == BACKGROUND_WEIGHT for w in weights)

    def test_empty_person_list_returns_empty(self):
        mgr = ActivePersonFocusManager()
        assert mgr.compute_weights("ptrk_1", [], set()) == []

    def test_every_tracked_person_gets_exactly_one_weight(self):
        mgr = ActivePersonFocusManager()
        ids = ["ptrk_1", "ptrk_2", "ptrk_3"]
        weights = mgr.compute_weights("ptrk_2", ids, set())
        assert len(weights) == 3
        assert {w.person_track_id for w in weights} == set(ids)
