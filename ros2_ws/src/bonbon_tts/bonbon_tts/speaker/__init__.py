"""bonbon_tts.speaker — HAL speaker abstraction layer."""

from bonbon_tts.speaker.speaker_bridge import (
    AbstractSpeakerBridge,
    MockSpeakerBridge,
    SpeakerBridge,
)

__all__ = [
    "AbstractSpeakerBridge",
    "SpeakerBridge",
    "MockSpeakerBridge",
]
