"""bonbon_tts.speaker — HAL speaker abstraction layer."""
from bonbon_tts.speaker.speaker_bridge import (
    AbstractSpeakerBridge,
    SpeakerBridge,
    MockSpeakerBridge,
)

__all__ = [
    "AbstractSpeakerBridge",
    "SpeakerBridge",
    "MockSpeakerBridge",
]
