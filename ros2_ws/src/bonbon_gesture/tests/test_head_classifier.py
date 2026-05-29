"""
tests.test_head_classifier
============================
Unit tests for HeadGestureClassifier.

Injects synthetic alternating face-point sequences to verify that nod and
shake patterns are correctly detected.
"""

from __future__ import annotations

import sys
import os
import math
from typing import List, Tuple

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bonbon_gesture.classifiers.head_gesture_classifier import HeadGestureClassifier
from bonbon_gesture.config.gesture_config import GestureConfig


def _face(nose_x: float = 320.0, nose_y: float = 60.0) -> List[Tuple[float, float, float]]:
    """6-point face mesh with nose at (nose_x, nose_y)."""
    return [
        (nose_x, nose_y, 0.0),           # 0: nose_tip
        (nose_x - 20, nose_y - 15, 0.0), # 1: left eye
        (nose_x + 20, nose_y - 15, 0.0), # 2: right eye
        (nose_x - 15, nose_y + 20, 0.0), # 3: mouth left
        (nose_x + 15, nose_y + 20, 0.0), # 4: mouth right
        (nose_x, nose_y + 40, 0.0),      # 5: chin
    ]


class TestHeadGestureClassifier:

    def setup_method(self):
        config = GestureConfig(temporal_window=4)
        self.clf = HeadGestureClassifier(config)

    def test_no_face_returns_none(self):
        gesture, conf = self.clf.update(tracking_id=0, face_pts=None)
        assert gesture == "none"
        assert conf == 0.0

    def test_empty_face_returns_none(self):
        gesture, conf = self.clf.update(tracking_id=0, face_pts=[])
        assert gesture == "none"
        assert conf == 0.0

    def test_no_detection_before_history_fills(self):
        """Before 6 samples, classifier should not fire."""
        for i in range(5):
            gesture, _ = self.clf.update(tracking_id=0, face_pts=_face(nose_y=60.0))
        assert gesture == "none"

    def test_nod_detected_with_y_oscillation(self):
        """Alternating large y values (up-down-up) → head_nod_yes."""
        clf = HeadGestureClassifier(GestureConfig(temporal_window=4))
        detected = False
        # Inject 12 frames of sinusoidal y oscillation with 25px amplitude
        for i in range(12):
            ny = 60.0 + 25.0 * math.sin(i * 1.0)
            gesture, conf = clf.update(tracking_id=1, face_pts=_face(nose_y=ny))
            if gesture == "head_nod_yes":
                detected = True
                assert conf >= 0.75
        assert detected, "head_nod_yes was never detected after 12 oscillating frames"

    def test_shake_detected_with_x_oscillation(self):
        """Alternating large x values (left-right-left) → head_shake_no."""
        clf = HeadGestureClassifier(GestureConfig(temporal_window=4))
        detected = False
        for i in range(12):
            nx = 320.0 + 25.0 * math.sin(i * 1.0)
            gesture, conf = clf.update(tracking_id=2, face_pts=_face(nose_x=nx))
            if gesture == "head_shake_no":
                detected = True
                assert conf >= 0.75
        assert detected, "head_shake_no was never detected after 12 oscillating frames"

    def test_no_nod_with_small_amplitude(self):
        """Small y oscillation (below threshold) should not produce a nod."""
        clf = HeadGestureClassifier(GestureConfig(temporal_window=4))
        for i in range(12):
            ny = 60.0 + 3.0 * math.sin(i * 1.2)  # 3px — below _NOD_AMPLITUDE_PX=15
            gesture, _ = clf.update(tracking_id=3, face_pts=_face(nose_y=ny))
            assert gesture != "head_nod_yes", f"Spurious nod at frame {i}"

    def test_no_shake_with_small_amplitude(self):
        """Small x oscillation should not produce a shake."""
        clf = HeadGestureClassifier(GestureConfig(temporal_window=4))
        for i in range(12):
            nx = 320.0 + 4.0 * math.sin(i * 1.2)  # 4px — below _SHAKE_AMPLITUDE_PX=20
            gesture, _ = clf.update(tracking_id=4, face_pts=_face(nose_x=nx))
            assert gesture != "head_shake_no", f"Spurious shake at frame {i}"

    def test_separate_tracking_ids_independent(self):
        """Two tracking IDs should not share history."""
        clf = HeadGestureClassifier(GestureConfig(temporal_window=4))
        # Person 0: large y oscillation
        for i in range(12):
            ny = 60.0 + 25.0 * math.sin(i * 1.0)
            clf.update(tracking_id=0, face_pts=_face(nose_y=ny))

        # Person 1: static face — should not get a nod
        for i in range(12):
            gesture, _ = clf.update(tracking_id=1, face_pts=_face(nose_y=60.0))
            assert gesture != "head_nod_yes", f"Person 1 got spurious nod at frame {i}"

    def test_reset_clears_history(self):
        """After reset(), history should be gone and no gesture fires."""
        clf = HeadGestureClassifier(GestureConfig(temporal_window=4))
        for i in range(10):
            clf.update(tracking_id=0, face_pts=_face(nose_y=60.0 + 25 * math.sin(i)))
        clf.reset(tracking_id=0)
        gesture, _ = clf.update(tracking_id=0, face_pts=_face(nose_y=80.0))
        assert gesture == "none"
