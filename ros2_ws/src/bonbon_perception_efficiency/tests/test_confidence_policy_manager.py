"""Tests for ConfidencePolicyManager."""

from __future__ import annotations

from bonbon_perception_efficiency.core.confidence_policy_manager import (
    ConfidenceFloor,
    ConfidencePolicyManager,
)


class TestNominal:
    def test_nominal_recommends_nominal_threshold(self):
        mgr = ConfidencePolicyManager()
        recs = mgr.recommend(degraded=False, safety_caution_or_above=False)
        gesture = next(r for r in recs if r.signal == "gesture")
        assert gesture.recommended_threshold == 0.65
        assert gesture.reason == "nominal"

    def test_covers_all_default_signals(self):
        mgr = ConfidencePolicyManager()
        recs = mgr.recommend(degraded=False, safety_caution_or_above=False)
        signals = {r.signal for r in recs}
        assert signals == {"gesture", "face", "voice", "text", "object"}


class TestDegradedMode:
    def test_degraded_raises_threshold(self):
        mgr = ConfidencePolicyManager()
        nominal = mgr.recommend(degraded=False, safety_caution_or_above=False)
        degraded = mgr.recommend(degraded=True, safety_caution_or_above=False)
        nominal_gesture = next(r for r in nominal if r.signal == "gesture")
        degraded_gesture = next(r for r in degraded if r.signal == "gesture")
        assert degraded_gesture.recommended_threshold > nominal_gesture.recommended_threshold

    def test_never_exceeds_one(self):
        mgr = ConfidencePolicyManager(floors=[ConfidenceFloor("x", 0.95, 0.5)])
        recs = mgr.recommend(degraded=True, safety_caution_or_above=True)
        assert recs[0].recommended_threshold <= 1.0


class TestSafetyElevated:
    def test_safety_elevated_raises_threshold(self):
        mgr = ConfidencePolicyManager()
        nominal = mgr.recommend(degraded=False, safety_caution_or_above=False)
        elevated = mgr.recommend(degraded=False, safety_caution_or_above=True)
        nominal_face = next(r for r in nominal if r.signal == "face")
        elevated_face = next(r for r in elevated if r.signal == "face")
        assert elevated_face.recommended_threshold > nominal_face.recommended_threshold


class TestNeverBelowMinimum:
    def test_recommendation_never_below_configured_minimum(self):
        mgr = ConfidencePolicyManager(floors=[ConfidenceFloor("custom", 0.5, 0.45)])
        recs = mgr.recommend(degraded=False, safety_caution_or_above=False)
        assert recs[0].recommended_threshold >= 0.45


class TestFloorLookup:
    def test_floor_for_known_signal(self):
        mgr = ConfidencePolicyManager()
        floor = mgr.floor_for("gesture")
        assert floor is not None
        assert floor.nominal_threshold == 0.65

    def test_floor_for_unknown_signal_returns_none(self):
        mgr = ConfidencePolicyManager()
        assert mgr.floor_for("nonexistent") is None
