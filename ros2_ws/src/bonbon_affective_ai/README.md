# bonbon_affective_ai

**Multi-modal emotion recognition** for the BonBon service robot. Fuses facial
expression, vocal tone, and text sentiment into a single, smoothed
`HumanEmotionState` with a recommended interaction style — so the behaviour
engine can respond with appropriate empathy, patience and social distance.

This package is **perception only**: it observes and infers emotion, it never
acts. All heavy ML backends are optional and degrade to deterministic mocks so
the whole pipeline runs in simulation with no models installed.

---

## Responsibilities

| Capability | Module |
|---|---|
| Facial-expression emotion (7 classes) | `analyzers/face_emotion_analyzer.py` |
| Vocal-tone emotion (arousal/valence) | `analyzers/voice_emotion_analyzer.py` |
| Text sentiment + emergency/distress keywords | `analyzers/text_emotion_analyzer.py` |
| Weighted multi-modal fusion + response-style recommendation | `fusion/emotion_fusion_engine.py` |
| Temporal smoothing / state stability | `fusion/temporal_smoother.py` |
| Privacy suppression (face/voice) | `privacy/privacy_gate.py` |
| Pluggable backends (DeepFace / SpeechBrain / mock) | `backends/` |
| Health monitoring | `health/health_monitor.py` |
| ROS2 LifecycleNode orchestration | `nodes/affective_ai_node.py` |

---

## Architecture

```
/bonbon/vision/persons ─┐
/bonbon/speech/audio ───┤   ┌──────────── AffectiveAINode ────────────┐
/speech/command ────────┼──►│ FaceEmotionAnalyzer  ┐                  │
/bonbon/safety/state ───┘   │ VoiceEmotionAnalyzer ├─► EmotionFusion  │
                            │ TextEmotionAnalyzer  ┘    Engine        │
                            │ PrivacyGate (gates face/voice)          │
                            │ TemporalSmoother (state stability)      │
                            └──────────────────────────────────────────┘
                                          │
                                          ▼
                            /bonbon/affective/state (HumanEmotionState)
```

### Fusion weighting

The fused state is a confidence-weighted vote across modalities (configurable in
`affective_config.py`). **Emergency overrides** short-circuit the weighting:
- `text.emergency_detected` → state `urgent`, operator alert raised.
- gesture `fallen_posture` / `stop_palm` → state `urgent`, operator alert raised.

Each fused state maps to a recommended **response style**, **TTS emotion**,
**interaction distance**, and **patience multiplier** consumed by
`bonbon_behavior_engine` and `bonbon_tts`.

---

## Topics & Services

### Subscribed
| Topic | Type | Purpose |
|---|---|---|
| `/bonbon/vision/persons` | `bonbon_msgs/PersonStateArray` | face crops / person context |
| `/bonbon/speech/audio` | `bonbon_msgs/AudioChunk` | vocal-tone analysis |
| `/speech/command` | `bonbon_msgs/SpeechCommand` | text sentiment |
| `/bonbon/safety/state` | `bonbon_msgs/SafetyState` | safety context |

### Published
| Topic | Type | Purpose |
|---|---|---|
| `/bonbon/affective/state` | `bonbon_msgs/HumanEmotionState` | fused emotion + recommendations |

### Services
| Service | Type | Purpose |
|---|---|---|
| `~/analyze_text` | `bonbon_srvs/AnalyzeText` | one-shot text emotion analysis |
| `~/set_privacy_mode` | `bonbon_srvs/SetPrivacyMode` | suppress face/voice analysis |
| `~/health_check` | `bonbon_srvs/HealthCheck` | health snapshot |

---

## Privacy

`PrivacyGate` enforces three levels:
- `normal` — all modalities active.
- `face_only` / `voice_only` suppression — the suppressed modality returns a
  message with `privacy_suppressed=True` and **all scores explicitly zeroed**
  (never stale data).
- `suppressed` — face + voice suppressed; only text sentiment runs.

Raw audio/imagery is never stored; only derived scores are published.

---

## Backends (all optional)

| Modality | Real backend | Mock fallback |
|---|---|---|
| Face | DeepFace (`backends/deepface_backend.py`) | `mock_backends.py` |
| Voice | SpeechBrain wav2vec2 (`backends/speechbrain_backend.py`) | `mock_backends.py` |
| Text | rules-based (no ML, always available) | — |

If a real backend's import or model load fails, the analyzer logs a warning and
falls back to the mock — the node never crashes for a missing model.

---

## Running

```bash
cd ros2_ws && colcon build --packages-select bonbon_affective_ai
ros2 launch bonbon_affective_ai affective_ai.launch.py

# One-shot text analysis
ros2 service call /affective_ai_node/analyze_text bonbon_srvs/srv/AnalyzeText \
  "{text: 'help I fell down', person_id: 'p1'}"

# Watch fused state
ros2 topic echo /bonbon/affective/state
```

Runs fully in **mock mode** with no ML models: backends fall back to
deterministic mocks, so the fusion pipeline and message flow are identical.

---

## Testing

```bash
cd ros2_ws/src/bonbon_affective_ai
python -m pytest tests/ -q          # 101 tests
```

- `tests/conftest.py` installs one complete set of permissive ROS2/message
  stubs so the suite runs without rclpy. **Do not re-add per-file stubs** — the
  shared conftest is the single source of truth (see comment in that file).
- `test_face_emotion.py`, `test_voice_emotion.py`, `test_text_emotion.py` — analyzers
- `test_fusion.py` — weighted fusion + emergency override
- `test_affective_node.py` — node startup with mock backends
- `tests/integration/test_affective_integration.py` — full multi-modal fusion

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| All emotions `neutral` | Backends in mock mode, or low-confidence inputs | Install DeepFace/SpeechBrain, or check `~/health_check` for backend status. |
| `privacy_suppressed=True` always | Privacy level is face_only/voice_only/suppressed | Call `~/set_privacy_mode` to `normal`. |
| No `/bonbon/affective/state` output | No person / audio / text inputs arriving | Verify upstream vision + speech nodes are publishing. |
| Emergency not detected from text | Keyword not in the emergency list | See `text_emotion_analyzer.py` keyword sets; extend if needed. |
| Voice analysis always fails | SpeechBrain model not downloaded / no audio | Mock fallback is expected offline; check logs for the model path. |
| Test suite fails only when run together | A per-file stub re-introduced, clobbering conftest | Remove per-file `sys.modules` stubs; rely on `tests/conftest.py`. |

### Diagnostics

`~/health_check` reports which backend each analyzer is using (real vs mock),
the current privacy level, and per-modality availability. The fusion node logs
state transitions and always raises `requires_operator_alert` for emergency /
fallen-posture events.
