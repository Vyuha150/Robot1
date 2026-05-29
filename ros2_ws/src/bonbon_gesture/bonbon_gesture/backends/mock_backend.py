"""
bonbon_gesture.backends.mock_backend
======================================
Deterministic mock backend for unit tests and CI environments where MediaPipe
is unavailable.

The mock generates a realistic standing-person pose (33 MediaPipe landmarks)
and neutral hand/face landmarks.  When ``test_scenario`` mode is enabled it
cycles through a predefined list of gesture scenarios on every call so that
downstream classifiers, smoothers and tests can exercise the full pipeline
without a camera.

Scenario cycle (repeating):
  0: neutral          — arms at sides, no hands visible
  1: raised_hand      — right wrist above right shoulder
  2: stop_palm        — all fingers extended, palm forward
  3: wave             — open right hand at shoulder height
  4: pointing_right   — right index extended, wrist to the right of nose
  5: thumbs_up        — right thumb up, other fingers curled
  6: head_nod_yes     — nose y oscillates (face mesh only, no hand change)
  7: head_shake_no    — nose x oscillates
"""

from __future__ import annotations

import logging
import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..config.gesture_config import GestureConfig
from .gesture_backend_interface import GestureBackendInterface, PersonLandmarks

_LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Base skeleton in normalised coordinates (0..1), scaled to a 640×480 frame
# ---------------------------------------------------------------------------
# MediaPipe pose landmark indices used here:
# 0=nose, 11=left_shoulder, 12=right_shoulder,
# 13=left_elbow, 14=right_elbow, 15=left_wrist, 16=right_wrist,
# 23=left_hip, 24=right_hip
# All other landmarks are set to plausible interpolated values.

_W, _H = 640, 480  # virtual frame size


def _standing_pose() -> List[Tuple[float, float, float, float]]:
    """Return 33 pose landmarks for a standing person centred in frame.

    Returns:
        List of 33 ``(x_px, y_px, z, visibility)`` tuples.
    """
    # Centre the person
    cx = _W / 2
    # Approximate y positions for key joints
    nose_y = _H * 0.12
    shoulder_y = _H * 0.28
    elbow_y = _H * 0.46
    wrist_y = _H * 0.60
    hip_y = _H * 0.58
    knee_y = _H * 0.75
    ankle_y = _H * 0.92

    shoulder_spread = _W * 0.12

    base: List[Tuple[float, float, float, float]] = []
    for i in range(33):
        if i == 0:   # nose
            base.append((cx, nose_y, 0.0, 0.99))
        elif i == 11:  # left shoulder
            base.append((cx - shoulder_spread, shoulder_y, 0.0, 0.99))
        elif i == 12:  # right shoulder
            base.append((cx + shoulder_spread, shoulder_y, 0.0, 0.99))
        elif i == 13:  # left elbow
            base.append((cx - shoulder_spread * 1.1, elbow_y, 0.0, 0.95))
        elif i == 14:  # right elbow
            base.append((cx + shoulder_spread * 1.1, elbow_y, 0.0, 0.95))
        elif i == 15:  # left wrist
            base.append((cx - shoulder_spread * 1.15, wrist_y, 0.0, 0.90))
        elif i == 16:  # right wrist
            base.append((cx + shoulder_spread * 1.15, wrist_y, 0.0, 0.90))
        elif i == 23:  # left hip
            base.append((cx - shoulder_spread * 0.6, hip_y, 0.0, 0.95))
        elif i == 24:  # right hip
            base.append((cx + shoulder_spread * 0.6, hip_y, 0.0, 0.95))
        elif i in (25, 27):  # left knee / ankle
            base.append((cx - shoulder_spread * 0.5, knee_y if i == 25 else ankle_y, 0.0, 0.90))
        elif i in (26, 28):  # right knee / ankle
            base.append((cx + shoulder_spread * 0.5, knee_y if i == 26 else ankle_y, 0.0, 0.90))
        else:
            base.append((cx, (nose_y + hip_y) / 2, 0.0, 0.80))
    return base


def _neutral_hand(cx: float, cy: float) -> List[Tuple[float, float, float]]:
    """Generate a closed-fist 21-point hand centred at (cx, cy).

    Returns:
        List of 21 ``(x_px, y_px, z)`` tuples.
    """
    pts: List[Tuple[float, float, float]] = []
    for i in range(21):
        # Rough fist shape — all fingertips near knuckles
        angle = (i / 21) * 2 * math.pi
        r = 10 + (i % 4) * 3
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle), 0.0))
    return pts


def _open_hand(cx: float, cy: float) -> List[Tuple[float, float, float]]:
    """Generate a spread open-palm 21-point hand centred at (cx, cy).

    Returns:
        List of 21 ``(x_px, y_px, z)`` tuples.
    """
    # Wrist at base; fingers extended upward
    pts: List[Tuple[float, float, float]] = []
    # Wrist (0)
    pts.append((cx, cy, 0.0))
    # 5 finger groups of 4 landmarks each: MCP, PIP, DIP, TIP
    finger_offsets_x = [-25, -12, 0, 12, 25]  # 5 fingers
    for fi in range(5):
        fx = cx + finger_offsets_x[fi]
        for joint in range(4):
            fy = cy - 15 - joint * 12
            pts.append((fx, fy, 0.0))
    return pts  # 21 points


def _pointing_hand(cx: float, cy: float) -> List[Tuple[float, float, float]]:
    """21-point hand with only the index finger extended.

    Returns:
        List of 21 ``(x_px, y_px, z)`` tuples.
    """
    pts = _neutral_hand(cx, cy)
    # Override index finger tip (landmark 8) to be above pip (landmark 6)
    pts[8] = (pts[8][0], cy - 40, 0.0)   # tip high
    pts[7] = (pts[7][0], cy - 25, 0.0)   # dip
    pts[6] = (pts[6][0], cy - 12, 0.0)   # pip
    return pts


def _thumbs_up_hand(cx: float, cy: float, is_right: bool = True) -> List[Tuple[float, float, float]]:
    """21-point hand with only thumb raised.

    Returns:
        List of 21 ``(x_px, y_px, z)`` tuples.
    """
    pts = _neutral_hand(cx, cy)
    # Thumb tip (4) above wrist (0): tip.x < pip.x for right hand
    offset = -15 if is_right else 15
    pts[4] = (cx + offset, cy - 35, 0.0)
    pts[3] = (cx + offset // 2, cy - 20, 0.0)
    return pts


def _neutral_face(cx: float, cy: float) -> List[Tuple[float, float, float]]:
    """6-point face mesh for a frontal face.

    Order: nose_tip, left_eye, right_eye, mouth_left, mouth_right, chin.

    Returns:
        List of 6 ``(x_px, y_px, z)`` tuples.
    """
    return [
        (cx, cy, 0.0),               # 0: nose tip
        (cx - 20, cy - 15, 0.0),     # 1: left eye
        (cx + 20, cy - 15, 0.0),     # 2: right eye
        (cx - 15, cy + 20, 0.0),     # 3: mouth left
        (cx + 15, cy + 20, 0.0),     # 4: mouth right
        (cx, cy + 40, 0.0),          # 5: chin
    ]


# Scenario names in order (for logging)
_SCENARIO_NAMES = [
    "neutral",
    "raised_hand",
    "stop_palm",
    "wave",
    "pointing_right",
    "thumbs_up",
    "head_nod_yes",
    "head_shake_no",
]
_NUM_SCENARIOS = len(_SCENARIO_NAMES)


class MockBackend(GestureBackendInterface):
    """Deterministic mock backend for testing the gesture pipeline.

    Args:
        config: Runtime gesture configuration.
        test_scenario: When True, cycle through gesture scenarios on each call
            so that downstream components are exercised.  When False every call
            returns a neutral standing pose.
    """

    def __init__(
        self,
        config: GestureConfig,
        test_scenario: bool = False,
    ) -> None:
        self._config = config
        self._test_scenario = test_scenario
        self._scenario_idx: int = 0
        self._call_count: int = 0
        self._nod_tick: int = 0   # drives nose y oscillation
        self._shake_tick: int = 0  # drives nose x oscillation
        self._ready = False

    # ------------------------------------------------------------------
    # GestureBackendInterface
    # ------------------------------------------------------------------

    def warmup(self) -> None:
        """Mock warmup — always succeeds immediately."""
        self._ready = True
        _LOG.info("MockBackend ready (test_scenario=%s).", self._test_scenario)

    def process_frame(self, bgr_frame: np.ndarray) -> List[PersonLandmarks]:
        """Return synthetic PersonLandmarks based on the current scenario.

        Args:
            bgr_frame: Input frame (used only to read image dimensions).

        Returns:
            A list containing one :class:`PersonLandmarks`.

        Raises:
            RuntimeError: If called before ``warmup()``.
        """
        if not self._ready:
            raise RuntimeError("MockBackend.process_frame() called before warmup().")

        h, w = bgr_frame.shape[:2] if bgr_frame is not None else (_H, _W)

        pose = _standing_pose()
        left_hand: Optional[List[Tuple[float, float, float]]] = None
        right_hand: Optional[List[Tuple[float, float, float]]] = None
        face_mesh = _neutral_face(_W / 2, _H * 0.12)

        if self._test_scenario:
            scenario = self._scenario_idx % _NUM_SCENARIOS
            _LOG.debug("MockBackend scenario: %s", _SCENARIO_NAMES[scenario])

            if scenario == 0:  # neutral
                pass

            elif scenario == 1:  # raised_hand
                # Move right wrist (index 16) well above right shoulder (12)
                rs = pose[12]
                pose[16] = (rs[0], rs[1] - 120, pose[16][2], 0.95)

            elif scenario == 2:  # stop_palm
                cx = _W / 2 + 76.8  # right side
                cy = _H * 0.28  # shoulder height
                right_hand = _open_hand(cx, cy)
                # Raise wrist to shoulder level
                rs = pose[12]
                pose[16] = (rs[0] + 10, rs[1] - 10, pose[16][2], 0.95)

            elif scenario == 3:  # wave
                cx = _W / 2 + 76.8
                cy = _H * 0.46  # elbow height
                right_hand = _open_hand(cx, cy)
                # Wrist above elbow
                pose[16] = (cx, pose[14][1] - 20, pose[16][2], 0.92)

            elif scenario == 4:  # pointing_right
                cx = _W / 2 + 76.8
                cy = _H * 0.46
                right_hand = _pointing_hand(cx, cy)
                # Wrist far right of nose
                pose[16] = (pose[0][0] + 120, pose[16][1], pose[16][2], 0.92)

            elif scenario == 5:  # thumbs_up
                cx = _W / 2 + 76.8
                cy = _H * 0.55
                right_hand = _thumbs_up_hand(cx, cy, is_right=True)

            elif scenario == 6:  # head_nod_yes — oscillate nose y
                amp = 20.0
                self._nod_tick += 1
                dy = amp * math.sin(self._nod_tick * 0.8)
                base = _neutral_face(_W / 2, _H * 0.12)
                face_mesh = [(p[0], p[1] + dy, p[2]) for p in base]

            elif scenario == 7:  # head_shake_no — oscillate nose x
                amp = 22.0
                self._shake_tick += 1
                dx = amp * math.sin(self._shake_tick * 0.8)
                base = _neutral_face(_W / 2, _H * 0.12)
                face_mesh = [(p[0] + dx, p[1], p[2]) for p in base]

            # Advance scenario every 6 calls (≈ 2 temporal windows)
            self._call_count += 1
            if self._call_count % 6 == 0:
                self._scenario_idx += 1

        return [
            PersonLandmarks(
                tracking_id=0,
                pose=pose,
                left_hand=left_hand,
                right_hand=right_hand,
                face_mesh=face_mesh,
                image_width=w,
                image_height=h,
            )
        ]

    @property
    def is_ready(self) -> bool:
        """True after ``warmup()`` is called."""
        return self._ready
