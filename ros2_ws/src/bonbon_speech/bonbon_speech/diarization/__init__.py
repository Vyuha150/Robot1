"""bonbon_speech.diarization — speaker diarization backends."""

from bonbon_speech.diarization.base_diarizer import (
    BaseDiarizer,
    DiarizationResult,
    SpeakerSegment,
)
from bonbon_speech.diarization.mock_diarizer import MockDiarizer

__all__ = ["BaseDiarizer", "DiarizationResult", "SpeakerSegment", "MockDiarizer"]
