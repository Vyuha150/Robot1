"""bonbon_gesture.backends — pluggable gesture-detection backends."""

from .gesture_backend_interface import GestureBackendInterface, PersonLandmarks
from .mediapipe_backend import MediaPipeBackend
from .mock_backend import MockBackend

__all__ = [
    "GestureBackendInterface",
    "PersonLandmarks",
    "MediaPipeBackend",
    "MockBackend",
]
