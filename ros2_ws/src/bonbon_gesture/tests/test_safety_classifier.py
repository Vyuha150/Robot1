"""
tests.test_safety_classifier
==============================
Unit tests for GestureSafetyClassifier.
"""

from __future__ import annotations

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bonbon_gesture.logic.safety_classifier import GestureSafetyClassifier


class TestGestureSafetyClassifier:

    def setup_method(self):
        self.clf = GestureSafetyClassifier()

    # ── Safety-relevant gestures ─────────────────────────────────────────────

    def test_stop_palm_safety_class(self):
        safety_relevant, safety_class, requires_immediate = self.clf.classify("stop_palm")
        assert safety_relevant is True
        assert safety_class == "stop"
        assert requires_immediate is True

    def test_fallen_posture_safety_class(self):
        safety_relevant, safety_class, requires_immediate = self.clf.classify("fallen_posture")
        assert safety_relevant is True
        assert safety_class == "alert"
        assert requires_immediate is True

    def test_raised_hand_safety_class(self):
        safety_relevant, safety_class, requires_immediate = self.clf.classify("raised_hand")
        assert safety_relevant is True
        assert safety_class == "alert"
        assert requires_immediate is False  # raised_hand is alert but not immediate

    def test_come_here_safety_class(self):
        safety_relevant, safety_class, requires_immediate = self.clf.classify("come_here")
        assert safety_relevant is True
        assert safety_class == "approach"
        assert requires_immediate is False

    def test_go_away_safety_class(self):
        safety_relevant, safety_class, requires_immediate = self.clf.classify("go_away")
        assert safety_relevant is True
        assert safety_class == "retreat"
        assert requires_immediate is False

    # ── Non-safety gestures ──────────────────────────────────────────────────

    def test_wave_not_safety_relevant(self):
        safety_relevant, safety_class, requires_immediate = self.clf.classify("wave")
        assert safety_relevant is False
        assert safety_class == "none"
        assert requires_immediate is False

    def test_thumbs_up_not_safety_relevant(self):
        safety_relevant, safety_class, _ = self.clf.classify("thumbs_up")
        assert safety_relevant is False
        assert safety_class == "none"

    def test_thumbs_down_not_safety_relevant(self):
        safety_relevant, safety_class, _ = self.clf.classify("thumbs_down")
        assert safety_relevant is False
        assert safety_class == "none"

    def test_unknown_gesture_not_safety_relevant(self):
        safety_relevant, safety_class, requires_immediate = self.clf.classify("unknown_gesture")
        assert safety_relevant is False
        assert safety_class == "none"
        assert requires_immediate is False

    def test_none_gesture(self):
        safety_relevant, safety_class, requires_immediate = self.clf.classify("none")
        assert safety_relevant is False
        assert safety_class == "none"
        assert requires_immediate is False

    def test_arbitrary_unknown_gesture(self):
        safety_relevant, safety_class, requires_immediate = self.clf.classify("robot_dance")
        assert safety_relevant is False
        assert safety_class == "none"

    # ── Convenience methods ──────────────────────────────────────────────────

    def test_is_safety_gesture_true(self):
        assert self.clf.is_safety_gesture("stop_palm") is True
        assert self.clf.is_safety_gesture("fallen_posture") is True
        assert self.clf.is_safety_gesture("raised_hand") is True

    def test_is_safety_gesture_false(self):
        assert self.clf.is_safety_gesture("wave") is False
        assert self.clf.is_safety_gesture("thumbs_up") is False
        assert self.clf.is_safety_gesture("none") is False

    def test_requires_immediate_true(self):
        assert self.clf.requires_immediate("stop_palm") is True
        assert self.clf.requires_immediate("fallen_posture") is True

    def test_requires_immediate_false(self):
        assert self.clf.requires_immediate("raised_hand") is False
        assert self.clf.requires_immediate("come_here") is False
        assert self.clf.requires_immediate("wave") is False

    # ── Return type correctness ──────────────────────────────────────────────

    def test_return_types(self):
        for gesture in ["stop_palm", "wave", "none", "unknown"]:
            result = self.clf.classify(gesture)
            assert isinstance(result, tuple)
            assert len(result) == 3
            safety_relevant, safety_class, requires_immediate = result
            assert isinstance(safety_relevant, bool)
            assert isinstance(safety_class, str)
            assert isinstance(requires_immediate, bool)
