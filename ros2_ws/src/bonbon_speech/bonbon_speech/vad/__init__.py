"""bonbon_speech.vad — voice activity detection."""
from bonbon_speech.vad.base_vad import BaseVAD, AudioSegment
from bonbon_speech.vad.mock_vad import MockVAD

__all__ = ["BaseVAD", "AudioSegment", "MockVAD"]
