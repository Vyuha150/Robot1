"""
bonbon_gesture.classifiers.hand_gesture_classifier
====================================================
Rules-based hand gesture classifier operating on 21-point MediaPipe hand
landmarks.

MediaPipe Hand landmark indices
---------------------------------
0  = wrist
1  = thumb_cmc   2  = thumb_mcp   3  = thumb_ip    4  = thumb_tip
5  = index_mcp   6  = index_pip   7  = index_dip   8  = index_tip
9  = middle_mcp  10 = middle_pip  11 = middle_dip  12 = middle_tip
13 = ring_mcp    14 = ring_pip    15 = ring_dip    16 = ring_tip
17 = pinky_mcp   18 = pinky_pip   19 = pinky_dip   20 = pinky_tip

Coordinate system: x increases to the right, y increases *downward* (image
convention).  Therefore a landmark with a smaller y-value is *higher* in the
image — i.e., the finger is more extended toward the top of the frame.
"""

from __future__ import annotations

from typing import List, Optional, Tuple


class HandGestureClassifier:
    """Classify a single hand from 21 MediaPipe hand landmarks.

    All methods are stateless; instantiate once and call ``classify``
    per frame per hand.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(
        self,
        hand_landmarks: Optional[List[Tuple[float, float, float]]],
        is_right: bool,
        pose_landmarks: Optional[List[Tuple[float, float, float, float]]] = None,
    ) -> Tuple[str, float]:
        """Classify the gesture shown by one hand.

        Args:
            hand_landmarks: 21-point landmark list in pixel space.
                Each element is ``(x_px, y_px, z_relative)``.  May be ``None``
                or shorter than 21 if the hand was not detected.
            is_right: True if this is the person's right hand (as seen from a
                forward-facing camera it appears on the *left* side of the
                image).
            pose_landmarks: Optional 33-point body pose for additional spatial
                context (currently unused; reserved for future wrist-motion
                analysis).

        Returns:
            A ``(gesture_name, confidence)`` tuple.
            ``gesture_name`` is one of: ``'stop_palm'``, ``'thumbs_up'``,
            ``'thumbs_down'``, ``'wave_candidate'``, ``'pointing'``, or
            ``'unknown_gesture'``.  ``confidence`` is in [0.0, 1.0].
        """
        if hand_landmarks is None or len(hand_landmarks) < 21:
            return ("none", 0.0)

        lm = hand_landmarks
        fingers_up = self._count_fingers_up(lm, is_right)

        # ── Stop palm ───────────────────────────────────────────────────
        # All five fingers extended and palm roughly facing the camera.
        if fingers_up == 5 and self._is_palm_facing_camera(lm):
            return ("stop_palm", 0.92)

        # ── Thumbs up ───────────────────────────────────────────────────
        if self._is_thumbs_up(lm, is_right):
            return ("thumbs_up", 0.88)

        # ── Thumbs down ─────────────────────────────────────────────────
        if self._is_thumbs_down(lm, is_right):
            return ("thumbs_down", 0.85)

        # ── Pointing ────────────────────────────────────────────────────
        # Index finger extended, other fingers curled.
        if self._is_pointing(lm, is_right):
            return ("pointing", 0.87)

        # ── Wave candidate ──────────────────────────────────────────────
        # Four or more fingers extended — final determination (wave vs open
        # palm) requires temporal context from the body classifier.
        if fingers_up >= 4:
            return ("wave_candidate", 0.70)

        return ("unknown_gesture", 0.30)

    # ------------------------------------------------------------------
    # Finger-counting helpers
    # ------------------------------------------------------------------

    def _count_fingers_up(self, lm: List[Tuple[float, float, float]], is_right: bool) -> int:
        """Count how many fingers are extended (pointing upward in the image).

        Args:
            lm: 21-point hand landmark list.
            is_right: True for the person's right hand.

        Returns:
            Number of extended fingers (0–5).
        """
        count = 0

        # ── Four fingers: compare tip y vs PIP y (smaller y = higher = up) ──
        tip_pip_pairs = [(8, 6), (12, 10), (16, 14), (20, 18)]
        for tip_idx, pip_idx in tip_pip_pairs:
            if lm[tip_idx][1] < lm[pip_idx][1]:
                count += 1

        # ── Thumb: compare x-axis because it extends sideways ───────────────
        # For a right hand (as labelled by MediaPipe) the thumb tip (4) is to
        # the *left* of the IP joint (3) when the thumb is extended outward.
        if is_right:
            if lm[4][0] < lm[3][0]:
                count += 1
        else:
            if lm[4][0] > lm[3][0]:
                count += 1

        return count

    def _is_palm_facing_camera(self, lm: List[Tuple[float, float, float]]) -> bool:
        """Heuristic check that the palm is oriented toward the camera.

        Uses the relative depth (z) of the wrist vs. knuckle landmarks.
        When z-depth is unreliable (no depth sensor) this always returns True
        to avoid false negatives on the safety-critical stop-palm gesture.

        Args:
            lm: 21-point hand landmark list.

        Returns:
            True when the palm appears to face the camera.
        """
        # z < 0 means closer to camera in MediaPipe's coordinate convention.
        # Wrist behind knuckles suggests a palm-forward orientation.
        wrist_z = lm[0][2]
        knuckle_z = (lm[5][2] + lm[9][2] + lm[13][2] + lm[17][2]) / 4
        if abs(wrist_z - knuckle_z) < 0.001:
            # No meaningful depth — assume facing camera (conservative for safety)
            return True
        return wrist_z >= knuckle_z  # wrist further from camera = palm forward

    # ------------------------------------------------------------------
    # Specific gesture helpers
    # ------------------------------------------------------------------

    def _is_thumbs_up(self, lm: List[Tuple[float, float, float]], is_right: bool) -> bool:
        """Detect the thumbs-up gesture.

        Criteria:
        * The thumb tip (4) is significantly above the wrist (0).
        * All four fingers (index–pinky) are curled (tips below PIPs).

        Args:
            lm: 21-point hand landmark list.
            is_right: True for the person's right hand.

        Returns:
            True when thumbs-up is detected.
        """
        # Thumb tip must be clearly above wrist; use 30% of wrist-to-middle-tip
        # distance as the threshold so the check scales with hand size.
        wrist_y = lm[0][1]
        middle_tip_y = lm[12][1]
        threshold = (wrist_y - middle_tip_y) * 0.30  # positive when middle above wrist
        thumb_up = lm[4][1] < wrist_y - threshold

        # All other fingers curled
        other_curled = all(
            lm[t][1] > lm[p][1]
            for t, p in zip([8, 12, 16, 20], [6, 10, 14, 18])
        )
        return thumb_up and other_curled

    def _is_thumbs_down(self, lm: List[Tuple[float, float, float]], is_right: bool) -> bool:
        """Detect the thumbs-down gesture.

        Criteria:
        * The thumb tip (4) is significantly below the wrist (0).
        * All four fingers are curled.

        Args:
            lm: 21-point hand landmark list.
            is_right: True for the person's right hand.

        Returns:
            True when thumbs-down is detected.
        """
        wrist_y = lm[0][1]
        middle_tip_y = lm[12][1]
        threshold = abs(wrist_y - middle_tip_y) * 0.30
        thumb_down = lm[4][1] > wrist_y + threshold

        other_curled = all(
            lm[t][1] > lm[p][1]
            for t, p in zip([8, 12, 16, 20], [6, 10, 14, 18])
        )
        return thumb_down and other_curled

    def _is_pointing(self, lm: List[Tuple[float, float, float]], is_right: bool) -> bool:
        """Detect a pointing gesture (index finger extended, rest curled).

        Args:
            lm: 21-point hand landmark list.
            is_right: True for the person's right hand.

        Returns:
            True when pointing is detected.
        """
        index_up = lm[8][1] < lm[6][1]  # index tip above PIP
        # Middle, ring, pinky must be curled
        others_curled = all(
            lm[t][1] > lm[p][1]
            for t, p in zip([12, 16, 20], [10, 14, 18])
        )
        return index_up and others_curled
