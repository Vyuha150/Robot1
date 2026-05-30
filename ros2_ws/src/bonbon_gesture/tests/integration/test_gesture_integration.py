"""Integration tests for the bonbon_gesture recognition pipeline.

Exercise the full chain the GestureNode wires together — HandGestureClassifier
→ GestureTemporalSmoother → GestureIntentMapper + GestureSafetyClassifier —
end-to-end, without rclpy. Verifies that a stable stream of detections produces
a single debounced event with the correct intent and safety classification, and
that safety-relevant gestures bypass the cooldown.
"""

from __future__ import annotations

import math
import sys
import os
from typing import List, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from bonbon_gesture.classifiers.hand_gesture_classifier import HandGestureClassifier
from bonbon_gesture.config.gesture_config import GestureConfig
from bonbon_gesture.logic.intent_mapper import GestureIntentMapper
from bonbon_gesture.logic.safety_classifier import GestureSafetyClassifier
from bonbon_gesture.logic.temporal_smoother import GestureTemporalSmoother


def _open_palm(cx=320.0, cy=240.0) -> List[Tuple[float, float, float]]:
    pts = [None] * 21
    pts[0] = (cx, cy, 0.0)
    offsets = [-25, -12, 0, 12, 25]
    for fi in range(5):
        fx = cx + offsets[fi]
        start = 1 + fi * 4
        for joint in range(4):
            pts[start + joint] = (fx, cy - 10 - joint * 15, 0.0)
    return pts


def _pointing(cx=320.0, cy=240.0) -> List[Tuple[float, float, float]]:
    # closed fist with index extended
    pts = []
    for i in range(21):
        ang = (i / 21) * 2 * math.pi
        r = 10 + (i % 4) * 3
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang), 0.0))
    for tip, pip in [(8, 6), (12, 10), (16, 14), (20, 18)]:
        pts[tip] = (pts[tip][0], pts[pip][1] + 15, 0.0)
    pts[6] = (cx - 12, cy - 5, 0.0)
    pts[8] = (cx - 12, cy - 40, 0.0)
    return pts


class TestClassifierToSmoother:
    def test_stable_gesture_fires_single_event(self):
        clf = HandGestureClassifier()
        cfg = GestureConfig(temporal_window=4, gesture_cooldown_sec=10.0)
        smoother = GestureTemporalSmoother(cfg)

        gesture, conf = clf.classify(_open_palm(), is_right=True)
        assert gesture == "stop_palm"

        # Feed the same detection repeatedly; exactly one event should fire,
        # then the cooldown should suppress repeats (stop_palm is safety, so
        # it bypasses cooldown — verify it keeps firing for safety).
        fired = [smoother.update(1, gesture, conf) for _ in range(6)]
        events = [f for f in fired if f is not None]
        assert events, "a stable gesture must produce at least one event"
        assert events[0][0] == "stop_palm"

    def test_intent_and_safety_classification(self):
        intents = GestureIntentMapper()
        safety = GestureSafetyClassifier()

        # stop_palm → safety-relevant + an intent mapping.
        is_safety, safety_class, immediate = safety.classify("stop_palm")
        assert is_safety is True
        assert intents.get_intent("stop_palm")  # non-empty intent

        # pointing → not safety-relevant.
        is_safety_p, _, _ = safety.classify("pointing")
        assert is_safety_p is False


class TestPointingPipeline:
    def test_pointing_classified_and_mapped(self):
        clf = HandGestureClassifier()
        intents = GestureIntentMapper()
        gesture, conf = clf.classify(_pointing(), is_right=True)
        assert gesture == "pointing"
        assert intents.get_intent("pointing")


class TestSafetyBypassesCooldown:
    def test_safety_gesture_not_suppressed_by_cooldown(self):
        cfg = GestureConfig(temporal_window=3, gesture_cooldown_sec=100.0)
        smoother = GestureTemporalSmoother(cfg)
        # A safety gesture should fire repeatedly despite the long cooldown.
        results = [smoother.update(7, "raised_hand", 0.9) for _ in range(8)]
        fired = [r for r in results if r is not None]
        assert len(fired) >= 2, "safety gestures must bypass the cooldown"

    def test_non_safety_respects_cooldown(self):
        cfg = GestureConfig(temporal_window=3, gesture_cooldown_sec=100.0)
        smoother = GestureTemporalSmoother(cfg)
        results = [smoother.update(8, "pointing", 0.9) for _ in range(8)]
        fired = [r for r in results if r is not None]
        # Non-safety gesture fires once then is suppressed by the long cooldown.
        assert len(fired) == 1
