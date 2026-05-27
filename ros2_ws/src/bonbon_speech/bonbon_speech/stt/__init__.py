"""bonbon_speech.stt — speech-to-text backends."""

from bonbon_speech.stt.base_stt import BaseSTT, TranscriptionResult
from bonbon_speech.stt.mock_stt import MockSTT

__all__ = ["BaseSTT", "TranscriptionResult", "MockSTT"]
