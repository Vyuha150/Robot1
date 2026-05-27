"""bonbon_speech.vad — voice activity detection."""

from bonbon_speech.vad.base_vad import AudioSegment, BaseVAD
from bonbon_speech.vad.mock_vad import MockVAD

__all__ = ["BaseVAD", "AudioSegment", "MockVAD"]
