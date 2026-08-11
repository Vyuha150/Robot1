# Three-Pi Runtime Audit

Edge AI Runtime brief, Phase 1. Ground truth for Phase 10 (board
allocation) before any new config is written.

## Existing distributed config (`config/distributed/`, 7 files)

`cyclonedds_ethernet_profile.xml`, `failure_policy.yaml`,
`pi_human_ai.yaml`, `pi_navigation_safety.yaml`, `pi_ui_api.yaml`,
`robot_network.yaml`, `topic_contracts.yaml`.

Naming note: this brief's "UI/Supervisor Pi" = `pi_ui_api.yaml`'s
`ui_api` role; "AI Interaction Pi" = `pi_human_ai.yaml`'s `human_ai`
role; "Navigation/Safety Pi" = `pi_navigation_safety.yaml`'s
`navigation_safety` role. Same three-Pi split as the brief, different
label vocabulary — Phase 10 should map onto these, not invent parallel
role names.

- **`robot_network.yaml`**: `deployment_mode: three_pi`. Pi-1
  192.168.10.11 (`ui_api`), Pi-2 192.168.10.12 (`human_ai`), Pi-3
  192.168.10.13 (`navigation_safety`, also chrony time server). ROS2
  domain 42, `rmw_cyclonedds_cpp`, wired Ethernet only, unicast peer
  discovery. Heartbeat thresholds: `stale_after_sec: 1.5`,
  `lost_after_sec: 5.0`.
- **`pi_ui_api.yaml`** (Pi-1): packages `bonbon_operator_dashboard`,
  `bonbon_dashboard_api`. Explicit `forbidden:` list includes
  `direct_motor_control`, `camera_or_microphone_access`, `llm_hosting`.
  Never runs perception/LLM/audio/navigation/motor code.
- **`pi_human_ai.yaml`** (Pi-2, RPi5 8GB + AI HAT): packages
  `bonbon_oakd_vision`, `bonbon_respeaker_audio`, `bonbon_asr`,
  `bonbon_local_llm_gateway`, `bonbon_face_recognition`,
  `bonbon_multi_person_tracker`, `bonbon_object_intelligence`,
  `bonbon_gesture_intelligence`, `bonbon_affective_ai`,
  `bonbon_human_state_fusion`, `bonbon_tts`. `llm:` block: model
  `qwen2.5:0.5b`, `max_concurrent_requests: 1`, `max_output_tokens: 64`,
  `initial_timeout_sec: 1.0`, `cloud_api_fallback: false`,
  `resolution_order: [rule_engine, rag, llm]` (declared, **not enforced
  by any code** — see `EDGE_AI_GAP_ANALYSIS.md`). All motion output is
  `/bonbon/behavior/proposal` only — never a direct motor command.
- **`pi_navigation_safety.yaml`** (Pi-3): owns all physical motion
  authority. Packages `bonbon_navigation_bringup`, `bonbon_lidar_rplidar`,
  `bonbon_hal`, `bonbon_base_controller`, `bonbon_stepper_controller`,
  `bonbon_servo_controller`, `bonbon_motion_safety`,
  `bonbon_safety_supervisor`, `bonbon_navigation_monitor`.
  `authority.sole_motion_command_publisher: bonbon_safety_supervisor`;
  `actuation_starts_disabled: true`. Per `SAFETY_SEPARATION_AUDIT.md`,
  this stated authority is not yet what the code actually enforces for
  Nav2 goal dispatch.

### Stale-name finding

`pi_ui_api.yaml` references a package `bonbon_distributed_monitor` and a
`bonbon-distributed-monitor.service`, with its own inline note saying
this "was never actually built as such." Confirmed by repo-wide search:
**zero hits for `bonbon_distributed_monitor` anywhere in the repo.** The
real, live equivalent is `bonbon_distributed_safety`
(`core/heartbeat_monitor.py`) + `bonbon_authority_manager`
(`core/authority_manager.py`), bundled into
`deployment/systemd/pi1/bonbon-pi1-ros2-support.service`. Phase 10 should
either fix this stale reference or explicitly note it's intentionally
unresolved — building a *new* package under the old name would just add
a second stale reference.

## AI-Pi model load priority — already exists

`config/models/pi_ai_hat_plus_2_profile.yaml` lines 20-32:

```yaml
ai_pi_model_load_priority:
  - wake_word
  - vad
  - asr
  - person_detection
  - gesture_recognition
  - object_detection
  - tts
  - local_rag
  - local_llm
  - face_emotion
  - voice_emotion
  - speaker_diarization
```

This is explicitly documented as **boot-time warm-up order for Pi-2
only**, distinct from `pi_efficiency_profile.yaml`'s `priority_order`
(the safety-scoped shed order under load, described there as "tested,
10-scenario-proven... judged too risky to touch"). Phase 10 should
continue treating these as two separate lists for two separate purposes,
not merge them.

## Safety-scoped shed order (`config/pi_efficiency_profile.yaml`)

`priority_order` (lines 10-31): ranks 1-6 —
`safety_supervisor, emergency_stop, hal, lidar_obstacle_safety,
navigation_safety, active_person_tracking` — marked `safety_critical:
true`, never shed. Ranks 7-18 (shed first→last under pressure):
`object_detection, person_detection, gesture_recognition, speech_vad,
stt, human_state_fusion, tts, dashboard, rag, llm, background_emotion,
analytics_logging`. `event_gated:` block: `stt: speech_detected`,
`llm: stable_intent`, `rag: cache_miss`, `face_emotion: active_person`,
`voice_emotion: speech_segment`. Thresholds: `cpu_overload_percent: 90`,
`cpu_caution_percent: 75`, `memory_pressure_percent: 85`,
`cpu_temp_caution_c: 75`, `cpu_temp_fault_c: 90`,
`degraded_sustained_sec: 10` — single source of truth, mirrored
consistently by `bonbon_safety`, `bonbon_perception_efficiency`, and
`bonbon_llm` (verified, not just claimed — same numbers appear in all
three).

This priority ordering already matches the brief's Phase 8 "Highest /
Medium / Lower priority" tiers closely (safety tier 1-6 = brief's
"Highest priority"; VAD/ASR/tracking/gesture/detection/TTS = brief's
"Medium priority"; RAG/LLM/emotion/analytics = brief's "Lower
priority"). Phase 8's `inference_scheduler.py` should read this existing
config, not hardcode a parallel ordering.

## Systemd services (three-Pi layer already deployed)

`deployment/systemd/pi1/` (3): `bonbon-pi1-dashboard-api.service`,
`bonbon-pi1-dashboard-frontend.service`, `bonbon-pi1-ros2-support.service`.

`deployment/systemd/pi2/` (8): `bonbon-pi2-asr.service`,
`bonbon-pi2-behavior-engine.service`,
`bonbon-pi2-distributed-liveness.service`, `bonbon-pi2-hal.service`,
`bonbon-pi2-llm.service`, `bonbon-pi2-perception-fusion.service`,
`bonbon-pi2-tts.service`, `bonbon-pi2-vision.service`.

`deployment/systemd/pi3/` (7): `bonbon-pi3-actuation.service`,
`bonbon-pi3-base-controller.service`,
`bonbon-pi3-distributed-liveness.service`, `bonbon-pi3-hal.service`,
`bonbon-pi3-motion-gateway.service`, `bonbon-pi3-navigation.service`,
`bonbon-pi3-safety.service`.

A flat/legacy set of 11 `.service` files also exists directly under
`deployment/systemd/` (pre-three-Pi split) — Phase 10's new
`scripts/edge_ai/start_*.sh` should target the per-Pi units above, not
the legacy flat ones, to avoid a fourth systemd layer.

## Compose files

`deployment/compose/`: `docker-compose.dev.yml`,
`docker-compose.pi1.yml`, `docker-compose.pi2.yml`,
`docker-compose.pi3.yml`, `docker-compose.robot.yml`,
`docker-compose.simulation.yml` — already per-Pi. No new compose files
needed for Phase 10; the new launch files/scripts should compose with
these, not replace them.

## Event-driven processing — already true for the two areas checked

- ASR: `bonbon_speech_ai/speech_pipeline.py::process_utterance` raises
  if `vad_confirmed` is not `True` — "ASR must never run continuously,
  only after a real VAD event." Already correct.
- Vision: `bonbon_vision/preprocessing/frame_throttler.py::FrameThrottler`
  is a token-bucket limiter wired into `vision_node.py`'s per-frame
  callback. Already correct.
- **Not yet confirmed event-driven**: gesture recognition —
  `bonbon_gesture/nodes/gesture_node.py` processes every incoming camera
  frame continuously (rate-bounded only by upstream vision throttling,
  not its own event gate). Phase 9 should verify whether this needs its
  own gate or whether upstream throttling is sufficient.

## Benchmark infrastructure already in place

`scripts/ai_models/benchmark_all_models.py` (drives
`bonbon_ai_model_registry`'s `BenchmarkRunner`), plus package-scoped
benchmarks: `bonbon_safety/tests/benchmarks/bench_hotpaths.py`,
`bonbon_vision/tests/benchmarks/bench_inference.py`,
`bonbon_speech/tests/benchmarks/bench_speech.py`,
`bonbon_perception_ai/tests/benchmarks/bench_perception.py`. Phase 14's
`benchmark_edge_ai_stack.py` should orchestrate/call into these rather
than reimplement per-capability benchmark logic that already exists.
`docs/AI_MODEL_BENCHMARK_REPORT.md` already exists with 3 real
benchmark runs (see that doc) — Phase 14 extends this pattern to the
system-level metrics (queue sizes, dropped frames, cache hit rate,
dashboard latency) that aren't covered yet, not duplicate the model-level
ones.
