# Performance Tuning

## ROS2

- Keep high-rate sensor topics on appropriate QoS profiles.
- Use reliable/transient-local QoS for safety state and e-stop state.
- Avoid blocking callbacks in lifecycle nodes.
- Monitor topic freshness, not only process liveness.
- Keep CPU-heavy AI inference isolated from safety and navigation processes.

## Navigation

- Tune Nav2 costmap inflation radius for the robot footprint.
- Keep safety margins conservative in hospitals/crowds.
- Tune recovery behavior timeouts in simulation before hardware rollout.
- Monitor replanning latency and recovery success rate.
- Use RTAB-Map database paths on persistent storage.

## Perception and AI

- Track perception latency, detection confidence, and stale frames.
- Use mock models for CI and real models for lab/staging.
- Keep model volumes read-only in production.
- Watch memory growth during long-duration runs.

## Speech and TTS

- Monitor STT latency and confidence.
- Use noise profiles in simulation before noisy deployments.
- Track TTS queue length and emergency announcement latency.

## Data Stores

- Keep SQLite databases on reliable storage.
- Run periodic backups.
- Track vector/RAG index size and query latency.
- Apply privacy retention policies consistently.

## Deployment

- Use Docker layer caching in CI.
- Split CI into package matrices as the repo grows.
- Keep rollback artifacts on robot-local storage.
- Use Prometheus alerts for CPU, memory, disk, battery, stale topics, and safety events.

## Multi-Person Perception (bonbon_object_intelligence, bonbon_multi_person_tracker,
## bonbon_gesture, bonbon_speaker_intelligence, bonbon_human_state_fusion)

All five decision/fusion cores are bounded dict/list operations with no ML
inference inside them — measured p99 latency is low single-digit
milliseconds against budgets of 50–1000 ms (25–200x headroom). See
[`bench_hotpaths.py`](../ros2_ws/src/bonbon_safety/tests/benchmarks/bench_hotpaths.py)
for the live numbers (`python tests/benchmarks/bench_hotpaths.py` from
`ros2_ws/src/bonbon_safety`) and `perf_targets.py` for the budget catalogue.

| Budget | Target | Owner |
|---|---|---|
| `person_tracking_update` | ≤ 100 ms | `bonbon_multi_person_tracker` |
| `object_tracking_update` | ≤ 50 ms | `bonbon_object_intelligence` |
| `gesture_event` | ≤ 150 ms | `bonbon_gesture` |
| `speaker_turn_update` | ≤ 1000 ms | `bonbon_speaker_intelligence` (decision logic only — STT/diarization latency is `bonbon_speech`'s) |
| `human_state_fusion` | ≤ 100 ms | `bonbon_human_state_fusion` |

Because the decision layer has so much headroom, the actual end-to-end
latency budget is dominated by upstream ML inference, not this layer. Tune
these instead, on resource-constrained hardware (e.g. Raspberry Pi):

- **`bonbon_object_intelligence` / `bonbon_multi_person_tracker`**: lower
  `max_objects`/`max_persons` if the scene is genuinely crowded and CPU is
  tight — both are O(n×m) per cycle, so the resource bound directly caps
  worst-case latency.
- **`bonbon_gesture`**: raise `frame_sample_rate` (process every Nth frame)
  before touching anything else — gesture inference (MediaPipe), not the
  smoothing/assignment logic, is the actual bottleneck.
- **`bonbon_speaker_intelligence`**: nothing to tune here for latency — the
  dominant cost is `bonbon_speech`'s STT/diarization, which has its own
  `inference_timeout_sec` budget.
- **`bonbon_human_state_fusion`**: `publish_rate_hz` controls how often
  `build_all()` runs; lowering it trades responsiveness for CPU headroom,
  but the per-call cost is already negligible relative to anything else in
  the pipeline.
- **Vision-stale timeouts** (`vision_stale_timeout_sec` in both
  `bonbon_multi_person_tracker` and `bonbon_object_intelligence`): keep
  these above your camera's actual worst-case frame interval, or transient
  camera hiccups will spuriously age out tracked people/objects.
