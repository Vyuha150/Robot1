# bonbon_speech

ROS2 Humble speech-recognition module for the Bonbon service robot.

Converts raw microphone audio (from the Hardware Abstraction Layer) into
structured `SpeechCommand` events and rich `SpeechTranscription` messages.

---

## Architecture

```
/hal/audio  (AudioChunk)
      │
      ▼
┌──────────────────────────────────────────────────────────────────┐
│  SpeechNode  (LifecycleNode)                                     │
│                                                                  │
│  AudioPreprocessor ──► [WakeWordDetector] ──► AudioBuffer        │
│                                                     │            │
│                                               SileroVAD          │
│                                                     │ AudioSegment
│                                            WhisperSTT            │
│                                                     │ TranscriptionResult
│                                       [PyAnnoteDiarizer]         │
│                                                     │            │
│                        _publish_command() ◄──────────┘           │
│                        _publish_transcription()                  │
│                        _publish_health()  (1 Hz)                 │
└──────────────────────────────────────────────────────────────────┘
      │                    │                         │
      ▼                    ▼                         ▼
/speech/command   /speech/transcription    /health/speech
(SpeechCommand)  (SpeechTranscription)    (ModuleHealth)
```

The node is a **managed lifecycle node** — it progresses through
`unconfigured → inactive → active` before processing any audio.

---

## ROS2 Topics

| Direction | Topic | Message type | QoS |
|-----------|-------|--------------|-----|
| Subscribe | `/hal/audio` | `bonbon_msgs/AudioChunk` | best-effort, depth 10 |
| Publish   | `/speech/command` | `bonbon_msgs/SpeechCommand` | reliable, depth 10 |
| Publish   | `/speech/transcription` | `bonbon_msgs/SpeechTranscription` | reliable, depth 10 |
| Publish   | `/health/speech` | `bonbon_msgs/ModuleHealth` | reliable, depth 10 |

---

## Messages

### SpeechCommand (`bonbon_msgs/msg/SpeechCommand.msg`)
| Field | Type | Description |
|-------|------|-------------|
| `text` | string | Transcribed text |
| `language` | string | Detected language code (e.g. `"en"`, `"ja"`) |
| `confidence` | float32 | Model confidence 0–1 |
| `is_low_confidence` | bool | Below configured threshold |
| `is_timeout` | bool | STT timed out |
| `is_silence` | bool | VAD emitted but audio was silent |
| `wake_word_triggered` | bool | Wake-word gate was used |
| `speaker_id` | string | Dominant speaker label (e.g. `"SPEAKER_01"`) |
| `audio_duration_sec` | float32 | Duration of captured segment |
| `transcription_ms` | float32 | Total inference wall time |
| `doa_angle_deg` | float32 | Direction of arrival from HAL |

### SpeechTranscription (`bonbon_msgs/msg/SpeechTranscription.msg`)
Carries everything from `SpeechCommand` plus per-word timestamps, all
speaker IDs present in the segment, and the `vad_force_cut` flag.
Published only when `publish_transcription_detail: true`.

---

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `audio.sample_rate` | int | `16000` | Must be 8000 or 16000 Hz |
| `audio.chunk_size_samples` | int | `512` | HAL chunk size |
| `audio.max_buffer_sec` | float | `30.0` | Rolling buffer cap (privacy) |
| `audio.prebuffer_sec` | float | `0.5` | Pre-buffer before VAD onset |
| `vad.backend` | string | `"silero"` | `"silero"` or `"mock"` |
| `vad.model_path` | string | `""` | Local `.pt` path; empty = torch hub |
| `vad.start_threshold` | float | `0.50` | Voice onset probability |
| `vad.end_threshold` | float | `0.35` | Voice offset probability |
| `vad.min_speech_frames` | int | `8` | Minimum frames before emit |
| `vad.silence_frames_to_end` | int | `5` | Silence frames to close segment |
| `vad.max_speech_sec` | float | `15.0` | Force-cut long utterances |
| `vad.speech_pad_ms` | float | `300.0` | Pad each side of segment |
| `stt.backend` | string | `"mock"` | `"whisper"`, `"faster_whisper"`, or `"mock"` |
| `stt.model_size` | string | `"base"` | Whisper model size |
| `stt.model_dir` | string | `""` | Local cache dir; empty = default cache |
| `stt.device` | string | `""` | `"cpu"`, `"cuda"`, or `""` (auto) |
| `stt.language` | string | `""` | Force language; empty = auto-detect |
| `stt.confidence_threshold` | float | `0.50` | Below → `is_low_confidence` |
| `stt.inference_timeout_sec` | float | `15.0` | Per-utterance timeout |
| `stt.max_consecutive_timeouts` | int | `3` | Before STT enters degraded mode |
| `stt.word_timestamps` | bool | `false` | Enable per-word timestamps |
| `diarization.enabled` | bool | `false` | Enable speaker diarization |
| `diarization.backend` | string | `"mock"` | `"pyannote"` or `"mock"` |
| `diarization.hf_token` | string | `""` | HuggingFace token (never hardcoded) |
| `diarization.min_speakers` | int | `1` | Hint for pyannote |
| `diarization.max_speakers` | int | `5` | Hint for pyannote |
| `wake_word.enabled` | bool | `false` | Enable wake-word gate |
| `wake_word.backend` | string | `"mock"` | `"openwakeword"` or `"mock"` |
| `wake_word.keyword` | string | `"hey bonbon"` | Keyword label |
| `wake_word.model_path` | string | `""` | Local model file path |
| `wake_word.threshold` | float | `0.50` | Detection threshold |
| `wake_word.listen_timeout_sec` | float | `8.0` | Window after wake word |
| `privacy.store_audio` | bool | `false` | Write raw audio to disk |
| `privacy.anonymize_speaker` | bool | `false` | Replace all IDs with `SPEAKER_ANON` |
| `privacy.max_audio_retention_sec` | float | `30.0` | Buffer size cap |
| `publish_transcription_detail` | bool | `false` | Publish `SpeechTranscription` |
| `health_rate_hz` | float | `1.0` | Health publish frequency |
| `allow_degraded_startup` | bool | `false` | Continue if a backend fails to load |

---

## Backends

### VAD
| Backend | Package | Notes |
|---------|---------|-------|
| `silero` | `silero-vad` (torch hub) | Production — ships as `.pt` torch model |
| `mock` | (built-in) | Deterministic test/demo backend |

### STT
| Backend | Package | Notes |
|---------|---------|-------|
| `whisper` | `openai-whisper` | CPU inference, float32 |
| `faster_whisper` | `faster-whisper` | CTranslate2, INT8 — faster on CPU |
| `mock` | (built-in) | Deterministic test/demo backend |

### Diarization
| Backend | Package | Notes |
|---------|---------|-------|
| `pyannote` | `pyannote.audio` | Requires HuggingFace token via param |
| `mock` | (built-in) | Deterministic test/demo backend |

### Wake word
| Backend | Package | Notes |
|---------|---------|-------|
| `openwakeword` | `openwakeword` | Local inference, no cloud |
| `mock` | (built-in) | Deterministic test/demo backend |

---

## Package layout

```
bonbon_speech/
├── bonbon_speech/
│   ├── config/
│   │   ├── speech_config.py       # typed config hierarchy
│   │   └── speech_params.yaml     # default parameter values
│   ├── audio/
│   │   ├── audio_buffer.py        # thread-safe rolling ring buffer
│   │   └── audio_preprocessor.py # DC removal, normalisation, noise gate
│   ├── vad/
│   │   ├── base_vad.py            # AudioSegment + BaseVAD ABC
│   │   ├── silero_vad.py          # Silero VAD state machine
│   │   └── mock_vad.py            # deterministic mock
│   ├── stt/
│   │   ├── base_stt.py            # TranscriptionResult + BaseSTT ABC
│   │   ├── whisper_stt.py         # OpenAI Whisper / faster-whisper
│   │   └── mock_stt.py            # deterministic mock
│   ├── diarization/
│   │   ├── base_diarizer.py       # SpeakerSegment + DiarizationResult + ABC
│   │   ├── pyannote_diarizer.py   # pyannote.audio backend
│   │   └── mock_diarizer.py       # deterministic mock
│   ├── wake_word/
│   │   ├── wake_word_detector.py  # BaseWakeWordDetector + factory
│   │   ├── mock_wake_word.py      # deterministic mock
│   │   └── (openwakeword.py)      # openwakeword backend (optional)
│   └── nodes/
│       └── speech_node.py         # LifecycleNode — main entry point
├── launch/
│   └── speech.launch.py
└── tests/
    ├── test_audio_buffer.py
    ├── test_audio_preprocessor.py
    ├── test_vad.py
    ├── test_stt.py
    ├── test_diarization.py
    ├── test_wake_word.py
    ├── test_speech_node.py
    ├── integration/
    │   └── test_speech_integration.py
    └── benchmarks/
        └── bench_speech.py
```

---

## Privacy

All privacy controls are **opt-in** (disabled by default):

| Control | Parameter | Effect |
|---------|-----------|--------|
| Disable audio storage | `privacy.store_audio: false` | Raw audio is never written to disk |
| Buffer size cap | `privacy.max_audio_retention_sec: 30.0` | Rolling buffer evicts oldest samples |
| Speaker anonymisation | `privacy.anonymize_speaker: false` | Replaces all speaker IDs with `SPEAKER_ANON` |
| Buffer flush | `AudioBuffer.clear()` | Called on deactivate — wipes in-memory audio |

**HuggingFace token** for pyannote is never hardcoded. Inject it via:
```bash
ros2 param set /speech_node diarization.hf_token "hf_xxx..."
```

---

## Quick start

### 1. Run unit and integration tests (no ROS2 required)

```bash
cd ros2_ws/src/bonbon_speech
pip install numpy pytest

# All tests
pytest tests/ -v

# Integration tests only
pytest tests/integration/ -v
```

### 2. Run latency benchmarks

```bash
# Human-readable table (200 reps each)
python tests/benchmarks/bench_speech.py

# Quick mode (50 reps)
python tests/benchmarks/bench_speech.py --quick

# JSON output (for CI charting)
python tests/benchmarks/bench_speech.py --json

# Via pytest (enforces p99 budgets)
pytest tests/benchmarks/bench_speech.py -s -v
```

### 3. Launch with ROS2 (mock backends — no GPU required)

```bash
# Source workspace
source ros2_ws/install/setup.bash

# Launch with all-mock pipeline
ros2 launch bonbon_speech speech.launch.py \
    vad_backend:=mock \
    stt_backend:=mock

# Launch with real Whisper STT + Silero VAD
ros2 launch bonbon_speech speech.launch.py \
    vad_backend:=silero \
    stt_backend:=faster_whisper \
    stt_model_size:=small
```

### 4. Override a single parameter at runtime

```bash
ros2 param set /speech_node stt.confidence_threshold 0.65
ros2 param set /speech_node wake_word.enabled true
ros2 param set /speech_node diarization.enabled true
ros2 param set /speech_node diarization.hf_token "hf_yourtoken"
```

### 5. Monitor output

```bash
ros2 topic echo /speech/command
ros2 topic echo /health/speech
```

---

## Lifecycle management

```bash
# Configure
ros2 lifecycle set /speech_node configure

# Activate (starts audio processing)
ros2 lifecycle set /speech_node activate

# Deactivate (pauses, flushes audio buffer)
ros2 lifecycle set /speech_node deactivate

# Cleanup (tears down pipeline, releases model memory)
ros2 lifecycle set /speech_node cleanup
```

---

## STT timeout and degraded mode

If the STT backend exceeds `stt.inference_timeout_sec` on
`stt.max_consecutive_timeouts` successive calls, the backend enters
**degraded mode** (`stt.is_degraded = True`). Every subsequent segment
immediately returns `TranscriptionResult(is_timeout=True)` without
re-spawning a thread — protecting the audio callback from blocking.

Recover from degraded mode:
```python
node._stt.reset_degraded()
```
or restart the node via the lifecycle.

---

## Extending with a new backend

1. Subclass `BaseSTT` (or `BaseVAD`, `BaseDiarizer`, `BaseWakeWordDetector`).
2. Implement `_transcribe_impl(samples, sample_rate)` → `TranscriptionResult`.
3. The base class handles the `ThreadPoolExecutor`, timeout, consecutive-
   timeout counter, and `is_degraded` flag automatically.
4. Register the new backend key in `SpeechNode._make_stt()` (or equivalent
   factory function).

---

## Dependencies

### Production
| Package | Version | Purpose |
|---------|---------|---------|
| `numpy` | ≥1.23 | Audio array processing |
| `torch` | ≥2.0 | Silero VAD runtime |
| `openai-whisper` | ≥20231117 | Whisper STT |
| `faster-whisper` | ≥0.10 | CTranslate2 Whisper (optional) |
| `pyannote.audio` | ≥3.1 | Speaker diarization (optional) |
| `openwakeword` | ≥0.5 | Wake-word detection (optional) |

### Development / testing
| Package | Purpose |
|---------|---------|
| `pytest` | Test runner |
| `pytest-timeout` | Per-test timeout guard |

No GPU is required for any of the above when running with mock backends.
