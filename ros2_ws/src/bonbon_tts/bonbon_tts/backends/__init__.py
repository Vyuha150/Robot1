"""bonbon_tts.backends — TTS synthesis backend implementations."""

from bonbon_tts.backends.base_tts import BaseTTS, SynthesisOutput, TTSError
from bonbon_tts.backends.mock_tts import MockTTS
from bonbon_tts.backends.piper_tts import PiperTTS

__all__ = [
    "BaseTTS",
    "SynthesisOutput",
    "TTSError",
    "MockTTS",
    "PiperTTS",
]
