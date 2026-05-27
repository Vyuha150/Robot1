"""bonbon_tts.core — ROS2-free TTS pipeline components."""

from bonbon_tts.core.filler_player import FillerClip, FillerPlayer
from bonbon_tts.core.speech_synthesizer import SpeechSynthesizer
from bonbon_tts.core.tts_health import TTSHealthReport, TTSHealthTracker
from bonbon_tts.core.utterance_queue import Priority, Utterance, UtteranceQueue

__all__ = [
    "Priority",
    "Utterance",
    "UtteranceQueue",
    "TTSHealthReport",
    "TTSHealthTracker",
    "FillerClip",
    "FillerPlayer",
    "SpeechSynthesizer",
]
