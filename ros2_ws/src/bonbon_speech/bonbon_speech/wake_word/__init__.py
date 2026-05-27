"""bonbon_speech.wake_word — wake-word detection backends."""

from bonbon_speech.wake_word.mock_wake_word import MockWakeWordDetector
from bonbon_speech.wake_word.wake_word_detector import (
    BaseWakeWordDetector,
    make_wake_word_detector,
)

__all__ = [
    "BaseWakeWordDetector",
    "make_wake_word_detector",
    "MockWakeWordDetector",
]
