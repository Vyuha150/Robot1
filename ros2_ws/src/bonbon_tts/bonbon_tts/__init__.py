"""
bonbon_tts
==========
Speech synthesis module for the BonBon service robot.

Provides:
  - Piper TTS neural synthesis (subprocess or Python API)
  - Priority-based utterance queue with deduplication and expiry
  - Filler audio playback (pre-recorded clips played during long synthesis)
  - Emergency announcement priority (immediate interrupt of current speech)
  - Interruption handling (safe stop mid-utterance)
  - TTS failure fallback (beep/silence when Piper unavailable)
  - Speaker abstraction (HAL SpeakerDriver via SpeakerBridge)
  - Low-latency streaming: synthesis to tempfile → immediate play
  - Health reporting (latency, error rate, queue depth)

Architecture
------------
TTSNode (LifecycleNode)
  └─ SpeechSynthesizer           — orchestrates the full pipeline
       ├─ UtteranceQueue         — heapq priority queue, thread-safe
       ├─ PiperTTS / MockTTS     — synthesis backends (ABC BaseTTS)
       ├─ FillerPlayer           — plays short filler clips between synthesis
       ├─ SpeakerBridge          — HAL SpeakerDriver abstraction
       └─ TTSHealthTracker       — latency, error, and overflow counters

Priority Levels (lowest value = highest priority)
--------------------------------------------------
  EMERGENCY = 0  — safety alerts, path-clearing ("please move aside")
  HIGH      = 1  — navigation status ("going to table 3")
  NORMAL    = 2  — conversational responses
  LOW       = 3  — background status ("battery at 20 percent")

Security
--------
  * No API keys or voice model paths are hardcoded.
  * All paths injected via ROS2 parameters or TTSConfig.
"""

__version__ = "1.0.0"
__all__ = ["__version__"]
