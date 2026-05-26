# bonbon_tts — Speech Synthesis Module

Fast, priority-based TTS pipeline for the BonBon service robot.

## Architecture

```
ROS2 Topics                    TTS Core (ROS2-free)
─────────────                  ───────────────────────────────────
/bonbon/tts/say           ──►  UtteranceQueue  (heapq, thread-safe)
/bonbon/tts/say_priority  ──►       │
/bonbon/tts/emergency     ──►       ▼
                               SpeechSynthesizer  (worker thread)
                                    │
                          ┌─────────┴───────────┐
                          ▼                     ▼
                     PiperTTS              MockTTS (fallback)
                     (subprocess or API)   (beep WAV, stdlib only)
                          │
                          ▼
                    AbstractSpeakerBridge
                    ├── SpeakerBridge   (bonbon_hal.SpeakerDriver)
                    └── MockSpeakerBridge (tests)
                          │
                          ▼
                     Audio output (speaker / test double)
```

## Priority Levels

| Priority    | Value | Use case                                  |
|-------------|-------|-------------------------------------------|
| `EMERGENCY` | 0     | Safety alerts, obstacle in path           |
| `HIGH`      | 1     | Navigation status, urgent responses       |
| `NORMAL`    | 2     | Conversational replies (default)          |
| `LOW`       | 3     | Background status, battery percentage     |

Lower value = higher priority. Same-priority items are played FIFO.

## Features

- **Piper TTS** — fast offline neural synthesis; subprocess mode (default)
  or Python API mode.
- **Priority queue** — utterances are sorted by `(priority, enqueue_ts)`.
- **Deduplication** — set `dedup_key` to automatically replace stale
  status updates (e.g. repeated battery percentage announcements).
- **Staleness eviction** — utterances older than `max_age_sec` are dropped
  silently.
- **Interrupt handling** — `EMERGENCY` utterances immediately stop current
  playback.
- **TTS fallback** — when Piper is unavailable, `MockTTS` generates a beep
  WAV using only Python stdlib so the robot is never completely silent.
- **Filler audio** — short bridging clips ("one moment") while synthesis
  is in progress.
- **Health reporting** — latency statistics, error counts, fallback count
  published to `/bonbon/tts/health` (JSON).

## Quick Start

### Install

```bash
cd ~/ros2_ws
colcon build --packages-select bonbon_tts
source install/setup.bash
```

### Launch

```bash
# Default (mock speaker, no model required):
ros2 launch bonbon_tts tts.launch.py

# With a real Piper model:
ros2 launch bonbon_tts tts.launch.py \
    model_path:=/path/to/en_US-lessac-medium.onnx \
    speaker_driver:=hal \
    volume_pct:=85.0
```

### Speak something

```bash
# Plain text (NORMAL priority):
ros2 topic pub --once /bonbon/tts/say std_msgs/String "{data: 'Hello, I am BonBon.'}"

# Emergency interrupt:
ros2 topic pub --once /bonbon/tts/emergency std_msgs/String "{data: 'Warning: obstacle detected.'}"

# Priority + dedup (JSON):
ros2 topic pub --once /bonbon/tts/say_priority std_msgs/String \
  "{data: '{\"text\": \"Battery 20%\", \"priority\": \"LOW\", \"dedup_key\": \"battery\"}'}"

# Clear queue:
ros2 service call /bonbon/tts/clear_queue std_srvs/Empty
```

## Configuration

All parameters are set in `config/tts_params.yaml` and can be overridden
at launch time.

### Piper model download

```bash
# Download a voice model from Piper releases:
mkdir -p ~/piper_models
cd ~/piper_models
wget https://github.com/rhasspy/piper/releases/download/v1.2.0/en_US-lessac-medium.onnx
wget https://github.com/rhasspy/piper/releases/download/v1.2.0/en_US-lessac-medium.onnx.json
```

### Key parameters

| Parameter                    | Default                  | Description                            |
|------------------------------|--------------------------|----------------------------------------|
| `piper.model_path`           | `""`                     | Absolute path to `.onnx` model file    |
| `piper.use_subprocess`       | `true`                   | Subprocess vs Python API mode          |
| `piper.length_scale`         | `1.0`                    | Speaking rate (>1 = slower)            |
| `filler.enabled`             | `true`                   | Enable filler clips                    |
| `filler.cooldown_sec`        | `3.0`                    | Min seconds between filler plays       |
| `queue.max_depth`            | `32`                     | Max queued utterances                  |
| `speaker.driver`             | `"mock"`                 | `"mock"` or `"hal"`                    |
| `speaker.volume_pct`         | `80.0`                   | Playback volume (0–100)                |
| `health_rate_hz`             | `1.0`                    | Health topic publish rate              |

## Running Tests

```bash
cd ros2_ws/src/bonbon_tts
pytest tests/ -v
```

No ROS2, Piper, or audio device required — all tests use `MockTTS` and
`MockSpeakerBridge`.

```
tests/test_tts_config.py          — config dataclasses, from_dict, validate
tests/test_utterance_queue.py     — priority queue, dedup, overflow, staleness
tests/test_tts_health.py          — health tracker, latency stats, p95
tests/test_filler_player.py       — clip loading, maybe_play, cooldown
tests/test_speaker_bridge.py      — MockSpeakerBridge record/reset
tests/test_speech_synthesizer.py  — synthesis, fallback, interrupt, health
tests/integration/
  test_tts_pipeline.py            — end-to-end pipeline tests
```

## Programmatic Usage (ROS2-free)

```python
from bonbon_tts.backends.mock_tts import MockTTS
from bonbon_tts.core.speech_synthesizer import SpeechSynthesizer
from bonbon_tts.core.utterance_queue import Utterance, Priority
from bonbon_tts.speaker.speaker_bridge import MockSpeakerBridge

synth = SpeechSynthesizer(
    primary_tts = MockTTS(),
    speaker     = MockSpeakerBridge(),
)
synth.start()
synth.say(Utterance(text="Hello!", priority=Priority.HIGH))
synth.wait_until_idle(timeout=5.0)
synth.stop()
```

## Security Constraints

- **No model paths or credentials hardcoded** — all injected via ROS2
  parameters or `TTSConfig`.
- **Audio privacy** — `privacy.store_audio=False` default; raw audio
  is never written to disk unless explicitly enabled.
- **No direct `/cmd_vel` access** — TTS never publishes velocity commands.

## Package Layout

```
bonbon_tts/
├── bonbon_tts/
│   ├── config/
│   │   └── tts_config.py         # TTSConfig, PiperConfig, …
│   ├── backends/
│   │   ├── base_tts.py           # BaseTTS ABC, SynthesisOutput, TTSError
│   │   ├── piper_tts.py          # PiperTTS (subprocess + API modes)
│   │   └── mock_tts.py           # MockTTS (beep WAV, test double)
│   ├── core/
│   │   ├── utterance_queue.py    # Priority, Utterance, UtteranceQueue
│   │   ├── tts_health.py         # TTSHealthTracker, TTSHealthReport
│   │   ├── filler_player.py      # FillerPlayer
│   │   └── speech_synthesizer.py # SpeechSynthesizer (worker thread)
│   ├── speaker/
│   │   └── speaker_bridge.py     # AbstractSpeakerBridge, SpeakerBridge, MockSpeakerBridge
│   └── nodes/
│       └── tts_node.py           # ROS2 LifecycleNode
├── config/
│   └── tts_params.yaml           # Default ROS2 parameters
├── launch/
│   └── tts.launch.py             # Launch + auto-configure/activate
└── tests/
    ├── test_tts_config.py
    ├── test_utterance_queue.py
    ├── test_tts_health.py
    ├── test_filler_player.py
    ├── test_speaker_bridge.py
    ├── test_speech_synthesizer.py
    └── integration/
        └── test_tts_pipeline.py
```
