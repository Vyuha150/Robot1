"""
bonbon_gesture.backends.mediapipe_backend
==========================================
MediaPipe Holistic backend for gesture landmark extraction.

Wraps ``mediapipe.solutions.holistic.Holistic`` which returns a single-person
pose + hands + face-mesh result per frame.  If ``mediapipe`` is not installed
the backend silently marks itself as not-ready so the node falls back to the
mock backend.

Notes
-----
* MediaPipe Holistic is a *single-person* model.  Multi-person tracking would
  require multiple independent instances or a different model.  This backend
  always returns at most one ``PersonLandmarks`` with ``tracking_id=0``.
* All landmark coordinates are scaled to pixel space of the input frame.
* The face mesh is simplified to 6 key points for the
  :class:`~bonbon_gesture.classifiers.head_gesture_classifier.HeadGestureClassifier`.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..config.gesture_config import GestureConfig
from .gesture_backend_interface import GestureBackendInterface, PersonLandmarks

_LOG = logging.getLogger(__name__)

# Key face-mesh indices (MediaPipe 478-point mesh)
# nose_tip=1, left_eye_centre=33, right_eye_centre=263,
# mouth_left=61, mouth_right=291, chin=152
_FACE_KEY_INDICES = [1, 33, 263, 61, 291, 152]


class MediaPipeBackend(GestureBackendInterface):
    """Gesture backend powered by MediaPipe Holistic.

    Args:
        config: Runtime gesture configuration.
    """

    def __init__(self, config: GestureConfig) -> None:
        self._config = config
        self._holistic = None  # type: ignore[assignment]
        self._mp = None
        self._ready = False
        # Simple hash-based person-ID map (reserved for future multi-person extension)
        self._person_id_map: Dict[int, int] = {}

    # ------------------------------------------------------------------
    # GestureBackendInterface
    # ------------------------------------------------------------------

    def warmup(self) -> None:
        """Import mediapipe and initialise the Holistic model."""
        try:
            import mediapipe as mp  # noqa: PLC0415

            self._mp = mp
            self._holistic = mp.solutions.holistic.Holistic(
                static_image_mode=False,
                model_complexity=1,
                smooth_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self._ready = True
            _LOG.info("MediaPipe Holistic backend initialised successfully.")
        except ImportError:
            _LOG.warning(
                "mediapipe package not found — MediaPipeBackend will not be ready. "
                "Install with: pip install mediapipe"
            )
            self._ready = False
        except Exception as exc:  # pragma: no cover
            _LOG.error("MediaPipe initialisation failed: %s", exc)
            self._ready = False

    def process_frame(self, bgr_frame: np.ndarray) -> List[PersonLandmarks]:
        """Run MediaPipe Holistic on *bgr_frame* and return landmarks.

        Args:
            bgr_frame: BGR uint8 image array (H, W, 3).

        Returns:
            A list containing exactly one :class:`PersonLandmarks` when at
            least one body part was detected, or an empty list otherwise.

        Raises:
            RuntimeError: If called before a successful ``warmup()``.
        """
        if not self._ready or self._holistic is None:
            raise RuntimeError(
                "MediaPipeBackend.process_frame() called before successful warmup(). "
                "Check that mediapipe is installed."
            )

        import cv2  # noqa: PLC0415

        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        results = self._holistic.process(rgb)

        h, w = bgr_frame.shape[:2]

        pose = self._extract_pose(results.pose_landmarks, h, w)
        left_hand = self._extract_hand(results.left_hand_landmarks, h, w)
        right_hand = self._extract_hand(results.right_hand_landmarks, h, w)
        face_mesh = self._extract_face(results.face_landmarks, h, w)

        # If nothing was detected at all, skip publishing to avoid noise
        if pose is None and left_hand is None and right_hand is None:
            return []

        landmarks = PersonLandmarks(
            tracking_id=0,
            pose=pose,
            left_hand=left_hand,
            right_hand=right_hand,
            face_mesh=face_mesh,
            image_width=w,
            image_height=h,
        )
        return [landmarks]

    @property
    def is_ready(self) -> bool:
        """True when mediapipe was imported and the model is loaded."""
        return self._ready

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_pose(
        self,
        pose_landmarks,
        h: int,
        w: int,
    ) -> Optional[List[Tuple[float, float, float, float]]]:
        """Convert MediaPipe pose landmarks to pixel-space tuples.

        Args:
            pose_landmarks: ``mediapipe.framework.formats.landmark_pb2.NormalizedLandmarkList``
                or ``None``.
            h: Frame height in pixels.
            w: Frame width in pixels.

        Returns:
            List of 33 ``(x_px, y_px, z_relative, visibility)`` tuples, or
            ``None`` if no landmarks were detected.
        """
        if pose_landmarks is None:
            return None
        return [
            (lm.x * w, lm.y * h, lm.z, lm.visibility)
            for lm in pose_landmarks.landmark
        ]

    def _extract_hand(
        self,
        hand_landmarks,
        h: int,
        w: int,
    ) -> Optional[List[Tuple[float, float, float]]]:
        """Convert MediaPipe hand landmarks to pixel-space tuples.

        Args:
            hand_landmarks: NormalizedLandmarkList for one hand, or ``None``.
            h: Frame height in pixels.
            w: Frame width in pixels.

        Returns:
            List of 21 ``(x_px, y_px, z_relative)`` tuples, or ``None``.
        """
        if hand_landmarks is None:
            return None
        return [
            (lm.x * w, lm.y * h, lm.z)
            for lm in hand_landmarks.landmark
        ]

    def _extract_face(
        self,
        face_landmarks,
        h: int,
        w: int,
    ) -> Optional[List[Tuple[float, float, float]]]:
        """Extract 6 key face-mesh points in pixel-space.

        Uses ``_FACE_KEY_INDICES`` = [nose_tip, left_eye, right_eye,
        mouth_left, mouth_right, chin].

        Args:
            face_landmarks: NormalizedLandmarkList (478-point mesh), or ``None``.
            h: Frame height in pixels.
            w: Frame width in pixels.

        Returns:
            List of up to 6 ``(x_px, y_px, z_relative)`` tuples, or ``None``
            if face was not detected.
        """
        if face_landmarks is None:
            return None
        pts = face_landmarks.landmark
        n = len(pts)
        result = [
            (pts[i].x * w, pts[i].y * h, pts[i].z)
            for i in _FACE_KEY_INDICES
            if i < n
        ]
        return result if result else None
