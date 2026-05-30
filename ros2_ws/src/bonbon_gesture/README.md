# bonbon_gesture

**Gesture recognition** for the BonBon service robot. Detects hand, body and
head gestures from the camera stream + person tracks, debounces them temporally,
maps them to interaction intents, and flags safety-relevant gestures (stop palm,
raised hand, fallen posture) for the behaviour engine and safety supervisor.

Perception only — it emits `GestureEvent` messages; it never commands motion.
MediaPipe is optional and falls back to a deterministic mock so the pipeline
runs in simulation with no models installed.

---

## Responsibilities

| Capability | Module |
|---|---|
| Hand-gesture classification (21-pt landmarks) | `classifiers/hand_gesture_classifier.py` |
| Body-gesture classification (33-pt pose) | `classifiers/body_gesture_classifier.py` |
| Head-gesture classification (nod / shake) | `classifiers/head_gesture_classifier.py` |
| Landmark extraction (MediaPipe / mock) | `backends/`, `processors/pose_landmark_processor.py` |
| Temporal smoothing / debounce / cooldown | `logic/temporal_smoother.py` |
| Gesture → interaction intent mapping | `logic/intent_mapper.py` |
| Safety-relevant gesture classification | `logic/safety_classifier.py` |
| Health monitoring | `health/health_monitor.py` |
| ROS2 LifecycleNode orchestration | `nodes/gesture_node.py` |

---

## Architecture

```
/bonbon/vision/camera/color/image_raw ─┐
/bonbon/vision/persons ────────────────┤  ┌──────── GestureNode ─────────┐
/bonbon/safety/state ───────────────────┼─►│ Backend → landmarks          │
                                         │  │   ↓                          │
                                         │  │ Hand / Body / Head classifier│
                                         │  │   ↓                          │
                                         │  │ TemporalSmoother (vote+cooldown)│
                                         │  │   ↓                          │
                                         │  │ IntentMapper + SafetyClassifier│
                                         │  └──────────────────────────────┘
                                         │              │
                                         ▼              ▼
                            /bonbon/gesture/events (GestureEvent)
                            /bonbon/gesture/status, /bonbon/diagnostics/events
```

### Recognised gestures

`stop_palm`, `thumbs_up`, `thumbs_down`, `pointing`, `wave_candidate`
(hand); `raised_hand`, `fallen_posture`, `arms_crossed` (body); `nod`, `shake`
(head). **Safety-relevant**: `stop_palm`, `raised_hand`, `fallen_posture` — these
bypass the debounce cooldown so they are never suppressed.

### Classifier robustness

The hand classifier uses an **orientation-independent thumb test** (thumb-tip
distance from the wrist vs. the MCP) and a **palm-size reference**
(wrist→middle-MCP) for thumbs-up/down thresholds — so it works regardless of
hand size or whether the thumb points up or sideways, and never depends on a
finger that must itself be curled.

---

## Topics & Services

### Subscribed
| Topic | Type | Purpose |
|---|---|---|
| `/bonbon/vision/camera/color/image_raw` | `sensor_msgs/Image` | frames for landmark extraction |
| `/bonbon/vision/persons` | `bonbon_msgs/PersonStateArray` | per-person association |
| `/bonbon/safety/state` | `bonbon_msgs/SafetyState` | safety context |

### Published
| Topic | Type | Purpose |
|---|---|---|
| `/bonbon/gesture/events` | `bonbon_msgs/GestureEvent` | debounced gesture events |
| `/bonbon/gesture/status` | `std_msgs/String` | node status (JSON) |
| `/bonbon/diagnostics/events` | `std_msgs/String` | diagnostics |

### Services
| Service | Type | Purpose |
|---|---|---|
| `/bonbon/gesture/health_check` | `bonbon_srvs/HealthCheck` | health snapshot |
| `/bonbon/gesture/set_enabled` | `std_srvs/SetBool` | enable/disable processing |

---

## Temporal smoothing

A gesture must win a majority vote across a sliding window
(`temporal_window`, default 4) before an event fires. After firing,
non-safety gestures are suppressed for `gesture_cooldown_sec` (default 1 s) to
avoid event spam. Safety gestures bypass the cooldown.

---

## Running

```bash
cd ros2_ws && colcon build --packages-select bonbon_gesture
ros2 launch bonbon_gesture gesture.launch.py

ros2 topic echo /bonbon/gesture/events
```

Runs in **mock mode** without MediaPipe: the mock backend emits deterministic
landmarks so the classify→smooth→map pipeline and message flow are identical.

---

## Testing

```bash
cd ros2_ws/src/bonbon_gesture
python -m pytest tests/ -q          # 54 tests
```

- `test_hand_classifier.py` — hand gestures, thumb orientation, palm size
- `test_body_classifier.py` — raised hand, fallen posture
- `test_head_classifier.py` — nod / shake
- `test_safety_classifier.py` — safety-relevant gesture mapping
- `tests/integration/test_gesture_integration.py` — classify→smooth→intent→safety

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No gesture events | No camera frames or person tracks | Start `bonbon_vision`; confirm `/bonbon/vision/persons`. |
| Gesture flickers / repeats | `temporal_window` too small / cooldown too short | Raise `temporal_window`, raise `gesture_cooldown_sec`. |
| Safety gesture missed | Window not converged, or below confidence | Safety gestures need ≥2 votes; check `confidence_threshold`. |
| `thumbs_up`/`down` not detected | Hand partially out of frame; thumb occluded | Ensure full hand visible; the classifier needs wrist + thumb + MCPs. |
| `stop_palm` not firing | Fewer than 5 fingers detected, or palm sideways | Show a flat, open palm toward the camera. |
| High CPU | MediaPipe Holistic at full frame-rate | Increase `frame_sample_rate`; lower `max_persons`. |
| Everything `unknown_gesture` | Landmarks malformed (mock vs real mismatch) | Verify backend; mock emits known-good landmarks. |

### Diagnostics

`/bonbon/gesture/health_check` reports the active backend (mediapipe vs mock),
processing latency, and per-frame gesture counts. Safety-relevant detections are
additionally logged at WARN and carry `is_safety_relevant=True` in the
`GestureEvent`.
