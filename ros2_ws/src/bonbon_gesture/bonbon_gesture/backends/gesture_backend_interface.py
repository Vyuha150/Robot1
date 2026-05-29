"""
bonbon_gesture.backends.gesture_backend_interface
===================================================
Abstract base class and shared data structures for gesture-detection backends.

All backends (MediaPipe, YOLO-pose, mock …) must subclass
``GestureBackendInterface`` and implement the two abstract methods so that
``GestureNode`` can swap backends without any changes to the pipeline.

PersonLandmarks format
-----------------------
All coordinates are in *pixel space* of the input frame unless otherwise noted.

* ``pose``       — 33 landmarks in MediaPipe Pose format.
                   Each element: (x_px, y_px, z_relative, visibility)
* ``left_hand``  — 21 landmarks (MediaPipe Hand format).
                   Each element: (x_px, y_px, z_relative)
* ``right_hand`` — same as left_hand
* ``face_mesh``  — 6 key-point simplified face mesh.
                   Indices: 0=nose_tip, 1=left_eye, 2=right_eye,
                            3=mouth_left, 4=mouth_right, 5=chin
                   Each element: (x_px, y_px, z_relative)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np


@dataclass
class PersonLandmarks:
    """All detected landmarks for a single person in one video frame.

    Attributes:
        tracking_id: Zero-based integer identifying this person within the
            current backend session.  For single-person backends (MediaPipe
            Holistic) this is always 0.
        pose: 33 pose landmarks or ``None`` when pose was not detected.
            Format per landmark: ``(x_px, y_px, z_relative, visibility)``.
        left_hand: 21 left-hand landmarks or ``None``.
            Format per landmark: ``(x_px, y_px, z_relative)``.
        right_hand: 21 right-hand landmarks or ``None``.
        face_mesh: 6 simplified face landmarks or ``None``.
            Format per landmark: ``(x_px, y_px, z_relative)``.
        image_width: Width of the source frame in pixels.
        image_height: Height of the source frame in pixels.
    """

    tracking_id: int
    pose: Optional[List[Tuple[float, float, float, float]]]
    left_hand: Optional[List[Tuple[float, float, float]]]
    right_hand: Optional[List[Tuple[float, float, float]]]
    face_mesh: Optional[List[Tuple[float, float, float]]]
    image_width: int
    image_height: int


class GestureBackendInterface(ABC):
    """Abstract interface for gesture landmark-detection backends.

    Concrete implementations must:
    1. Import their heavy dependencies lazily (inside ``warmup``) so that the
       package can be imported even when optional deps are absent.
    2. Never raise inside ``process_frame`` — return an empty list on failure.
    3. Set ``is_ready = False`` if required dependencies are unavailable so
       the node can fall back gracefully.
    """

    @abstractmethod
    def process_frame(self, bgr_frame: np.ndarray) -> List[PersonLandmarks]:
        """Detect landmark sets for all persons visible in *bgr_frame*.

        Args:
            bgr_frame: OpenCV-style BGR uint8 image array with shape
                ``(height, width, 3)``.

        Returns:
            A list of :class:`PersonLandmarks`, one entry per detected person.
            Returns an empty list if no persons are detected.

        Raises:
            RuntimeError: When called before ``warmup()`` completes
                successfully (``is_ready`` is False).
        """

    @abstractmethod
    def warmup(self) -> None:
        """Initialize the backend (load models, allocate GPU memory, etc.).

        This method is called once during the node's ``on_configure`` lifecycle
        transition.  It must not raise — log warnings instead and set
        ``is_ready = False`` on failure.
        """

    @property
    @abstractmethod
    def is_ready(self) -> bool:
        """True when ``warmup`` succeeded and the backend can process frames."""
