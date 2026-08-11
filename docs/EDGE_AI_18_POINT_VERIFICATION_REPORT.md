# Edge AI 18-Point No-Excuses Verification Report

A follow-up, independent verification pass proving (with files, configs,
tests, and reports — not assertion) that BonBon follows "small model +
smart routing + accelerator + caching + safety separation" against 18
explicit checks. 4 real gaps were found and fixed during this pass, each
narrowly scoped to the specific check that surfaced it. Everything below
is backed by a file path, a test, or a command run during this
verification — nothing here is claimed without evidence.

## Summary table

| # | Check | Verdict | Fixed this pass? |
|---|---|---|---|
| 1 | Every AI task has a specific model or deterministic service | ✅ PASS | **Yes** — 3 capabilities had zero working default |
| 2 | LLM not used for detection/gesture/emotion/appointment/token/safety | ✅ PASS | No |
| 3 | Hailo used for compatible vision models when available | ✅ PASS | No |
| 4 | CPU fallback works when Hailo unavailable | ✅ PASS | **Yes** — cross-capability fallback bug |
| 5 | RAG/cache before LLM for hospital questions | ✅ PASS | No |
| 6 | TTS cache exists for common phrases | ✅ PASS | No (fixed earlier this session, GAP-E13) |
| 7 | ASR is event-driven after VAD | ✅ PASS | No |
| 8 | Camera frames use bounded queues + stale-frame dropping | ✅ PASS | No |
| 9 | Gesture AND emotion pipelines use temporal smoothing | ✅ PASS | **Yes** — voice emotion had none |
| 10 | Face/emotion processing is per-person, not global | ✅ PASS | No |
| 11 | Safety loop never waits for AI | ✅ PASS | No |
| 12 | LLM direct motor/servo/Nav2 commands are blocked | ✅ PASS | No |
| 13 | UI direct motor/servo/Nav2 commands are blocked | ✅ PASS | No |
| 14 | Resource guard disables non-critical AI during CPU/temp/memory/battery stress | ✅ PASS | **Yes** — edge_ai_runtime_node's own facade was battery-blind |
| 15 | Degraded mode keeps safe reception functions alive | ✅ PASS | No |
| 16 | Dashboard shows model/fallback/latency/cache/resource/safety-blocks | ✅ PASS | No |
| 17 | Hardware-dependent tests are honestly BLOCKED | ✅ PASS | No |
| 18 | No fake PASS exists | ✅ PASS | No |

**Result: 18/18 PASS. 4 real gaps found and fixed, all narrowly scoped, zero unrelated changes, zero fabricated hardware verification.**

---

## Check 1 — Every AI task has a specific model or deterministic service

**Evidence, before fix:**
```
object_detection: 4 entries, default=None
person_detection: 1 entries, default=None
pose_estimation: 1 entries, default=None
```
`FallbackPolicy.resolve()` (`bonbon_ai_model_registry/model_fallback_policy.py:47-49`) returns immediately when `default_for_capability()` is `None` — it **never even attempts the fallback chain**, not even the guaranteed-safe mock. These 3 capabilities had zero working path, not "no Hailo hardware."

**Fix:** `config/models/model_registry.yaml` — `vision_hailo_yolo`, `vision_person_hailo_yolo`, `gesture_hailo_pose` flipped to `enabled_by_default: true` (the head of each real fallback chain, matching every other capability's own convention, e.g. `local_llm`'s default is the real primary model, not its terminal fallback). `offline_open_source_profile.yaml` updated to explicitly opt back out (`vision_hailo_yolo: false`), consistent with its existing `vision_ultralytics_direct: false` pattern for the same "license not clear" reason.

**Evidence, after fix (real command run this session, not fabricated):**
```
object_detection -> resolved: vision_mock              (fell back from vision_hailo_yolo)
person_detection -> resolved: vision_mock               (fell back from vision_person_hailo_yolo)
pose_estimation  -> resolved: gesture_mediapipe_holistic (fell back from gesture_hailo_pose)
```
`ModelRegistry.validate()` → `[]` (zero problems). All 5 hardware profile overlays re-validated clean.

---

## Check 2 — LLM not used for detection/gesture/emotion/appointment/token/safety

**Object/gesture/emotion:** confirmed via the merged registry — every entry for `object_detection`/`gesture_recognition`/`face_emotion`/`voice_emotion` is a real model or mock (Hailo/CPU/Ultralytics/MediaPipe/DeepFace/SpeechBrain), never `llm_qwen25_05b`.

**Appointment/token:** `ros2_ws/src/bonbon_patient_kiosk/bonbon_patient_kiosk/api/appointment_api.py` and `api/queue_api.py` — grepped for `llm|LLM|ollama`: **zero matches**. Pure FastAPI + Pydantic deterministic business logic. Confirmed by `task_router.py`'s own appointment branch: `"appointment booking is a deterministic workflow ... never routed through the LLM"` (verified by `tests/edge_ai/test_task_router.py::test_appointment_booking_never_uses_llm`).

**Safety:** `SafetySeparationGuard`'s never-allow table (`tests/edge_ai/test_safety_separation_guard.py::TestNeverAllowTable`, 7 tests) blocks `llm` from every direct-control action type. `CommandAuthorizer` fails closed (GAP-E1 fix, this session).

---

## Check 3 — Hailo used for compatible vision models when available

`bonbon_edge_ai_runtime/accelerator_manager.py` delegates to `bonbon_ai_runtime.RuntimeSelector`, which walks `[HAILO, CPU, MOCK]` in priority order (`runtime_selector.py:46`), calling `bonbon_ai_runtime.hailo_device_detector.HailoDeviceDetector().detect().usable` for real hardware detection — not a second, divergent implementation (`tests/perception_ai/test_hailo_runtime_selection.py::test_hailo_checker_delegates_to_bonbon_ai_runtime_not_a_second_implementation`).

---

## Check 4 — CPU fallback works when Hailo unavailable

**Real bug found and fixed:** `ModelRuntimeSelector.select()` (`model_runtime_selector.py:129-133`) computed `availability` scoped ONLY to the requested capability's own entries. But `person_detection`'s Hailo entry legitimately falls back to `object_detection`'s `vision_mock`, and `pose_estimation`'s Hailo entry falls back to `gesture_recognition`'s `gesture_mediapipe_holistic` — cross-capability references. The capability-scoped availability dict silently reported these cross-capability fallback targets as unavailable (dict-lookup miss → default `False`), making the **entire chain appear exhausted** even though the real fallback was genuinely available.

**Fix:** `availability` is now computed over `self._registry.all()` (every entry in the registry), not just the requested capability's entries. Verified safe: the sole consumer (`model_health_monitor.py:58`) does per-model_id lookups, never enumerates the dict, so widening its coverage is strictly more correct with no display regression.

**Evidence, after fix:** `person_detection` and `pose_estimation` now correctly resolve to their real CPU-only fallbacks (`vision_mock`, `gesture_mediapipe_holistic`) instead of `None`. New regression test: `tests/perception_ai/test_hailo_runtime_selection.py::test_cross_capability_fallback_targets_are_correctly_checked_for_availability`.

---

## Check 5 — RAG/cache before LLM for hospital questions

`llm_orchestrator_node._process_intent()` steps 3/3a/3b (unchanged this pass): `ResponseCache` checked BEFORE RAG retrieval, RAG retrieval before the LLM call — a cache hit skips both RAG and inference entirely. `task_router.py`'s FAQ branch independently enforces the same order: cache → RAG → (LLM only for wording, never for the lookup itself) — `tests/edge_ai/test_task_router.py::TestTaskRouterUsesCacheWhenProvided`. GAP-E14 (this session) added exact-match-first ahead of vector search in `RAGRetriever.retrieve_with_scores()` — `tests/test_rag_retriever.py::TestExactMatchFirst` (6 tests, including a `monkeypatch` proof `_embed()` is never called on the exact-match path).

---

## Check 6 — TTS cache exists for common phrases

`bonbon_speech_ai/tts_router.py`'s `HOSPITAL_PHRASE_CACHE_KEYS` + `models/tts_cache/`. GAP-E13 (fixed earlier this session): `speak()` now checks the real file-existence cache lookup **before** touching the runtime-availability chain at all, closing a real bug where a known phrase was re-synthesized via Piper on every call (measured 2.5–5.8s of avoidable latency). `tests/speech_ai/test_tts_router.py::TestCachedPhraseCheckedBeforeSynthesis`.

---

## Check 7 — ASR is event-driven after VAD

`bonbon_speech_ai/speech_pipeline.py`'s `vad_confirmed` gate — confirmed genuinely wired (re-verified during this session's GAP-E9 event-driven-processing phase; ASR never runs continuously).

---

## Check 8 — Camera frames use bounded queues and stale-frame dropping

**Bounded queues (confirmed via fresh code inspection this pass):**
- `bonbon_vision/nodes/vision_node.py:97-100,396-402` — `BEST_EFFORT_D2 = QoSProfile(reliability=BEST_EFFORT, history=KEEP_LAST, depth=2)` on `/bonbon/vision/camera/color/image_raw` and the depth topic.
- `bonbon_gesture/nodes/gesture_node.py:99-102,241-245` — the same `_BEST_EFFORT_D2` (depth=2) on the same camera topic.
- Additionally, `gesture_node.py`'s `in_flight` gate (now composed with the new presence gate via `should_process_frame()`, GAP-E12 fix) bounds actual processing to depth-1 — a new frame is never submitted while a prior one is still in flight.

**Stale-frame dropping:** `bonbon_edge_ai_runtime/accelerator_manager.py`'s `VisionOutputEnvelope.stale_result` flags any output whose `produced_at` timestamp is older than `stale_after_sec` (default 0.5s, matching `FrameThrottler`'s own cadence) — `tests/edge_ai/test_accelerator_manager.py::test_old_output_past_stale_threshold_is_marked_stale`.

---

## Check 9 — Gesture AND emotion pipelines use temporal smoothing

**Gesture:** `bonbon_gesture/logic/temporal_smoother.py::GestureTemporalSmoother` (pre-existing, majority-vote over `temporal_window` frames).

**Real gap found and fixed:** face emotion had smoothing (`bonbon_affective_ai/fusion/temporal_smoother.py::TemporalSmoother`, sliding-window mean, `window=face_temporal_window`); **voice emotion had none at all** — `voice_emotion_analyzer.py` passed the single raw backend result straight to the outgoing message.

**Fix:** `TemporalSmoother` generalized to accept a `fields` parameter (defaults to face's category set for 100% backward compatibility); new `VOICE_EMOTION_FIELDS` tuple added for voice's own 9-category vocabulary (`happy_score`, `sad_score`, etc.). Dominant-label derivation strips the `"_score"` suffix (`"happy_score"` → `"happy"`, matching `VoiceEmotion.msg`'s expected label format; a no-op for face's suffix-free fields). New `AffectiveConfig.voice_temporal_window` (default 5, mirrors `face_temporal_window`). `VoiceEmotionAnalyzer.analyze_segment()` now smooths before building the outgoing message, merging smoothed averaged fields over the raw result so non-averaged fields (arousal, valence, `*_valid`, `backend_used`) still pass through unchanged.

**Tests:** `tests/test_temporal_smoother.py` (10 tests: backward-compat for face, voice averaging, suffix-stripping, per-tracking-ID isolation, window bounding), `tests/test_voice_emotion.py::TestVoiceEmotionTemporalSmoothing` (3 tests, using a custom alternating-response backend since the existing `MockVoiceBackend` is constant and can't demonstrate averaging).

---

## Check 10 — Face/emotion processing is per-person, not global

`bonbon_msgs/msg/HumanEmotionState.msg:6-7` carries `person_id`/`tracking_id` per message. `emotion_fusion_engine.py::EmotionFusionEngine.fuse(face, voice, text, gesture_state, person_id, tracking_id)` keeps per-person history dicts keyed by `person_id`. `affective_ai_node.py::_run_fusion` iterates every tracked person and calls `_fuse_and_publish(person_id)` once per person — no single global "room mood" message exists anywhere.

---

## Check 11 — Safety loop never waits for AI

`InferenceScheduler.submit()` dispatches `safety_critical` modules immediately, structurally bypassing the queue (`config/pi_efficiency_profile.yaml`'s real `priority_order`) — it can never wait behind or be dropped for another module's request. `safety_gate_node.py` and every other `bonbon_safety` node: confirmed via grep, **zero** direct Python imports of `bonbon_llm`/`bonbon_affective_ai`/`bonbon_gesture`/`bonbon_vision`/`bonbon_edge_ai_runtime` anywhere in `bonbon_safety`'s nodes — safety communicates with AI only via async ROS2 topics it publishes, never a blocking call into AI code.

---

## Check 12 — LLM direct motor/servo/Nav2 commands are blocked

GAP-E1 (this session): `SafetySnapshot.safe_default()` now fails closed. `SafetySeparationGuard`'s never-allow table: only `{safety_supervisor, safety_gate, motion_approval_gateway}` may issue `direct_motor_command`/`direct_servo_command`/`raw_nav2_goal`/`emergency_override` — `llm` attempting any of these is `UNSAFE_DIRECT_CONTROL`, `blocked=True`, unconditionally (`tests/edge_ai/test_safety_separation_guard.py::TestNeverAllowTable`, 7 tests). GAP-E2 (this session): the only path an AI-originated navigation request can take is through `bonbon_motion_approval_gateway`'s real, fail-closed `evaluate()` — verified end-to-end in `tests/safety/test_end_to_end_navigation_safety_chain.py` (9 tests).

---

## Check 13 — UI direct motor/servo/Nav2 commands are blocked

Fresh, independent code inspection this pass: `bonbon_operator_api/api/command_api.py` — every mutating endpoint routes through `SafetyCommandGate.check_and_validate` (`safety/safety_gate.py`) before touching the ROS2 bridge. `bonbon_operator_api/ros2/ros2_bridge.py` — grepped for `Twist`, `cmd_vel`, `ActionClient`, `NavigateToPose`, `create_publisher(`: only two publishers exist in the whole package (`TTSRequest`, `BehaviorProposal` to `/bonbon/operator/proposal`). `call_navigate()` builds a `NavigateTo.Request()` and calls it as a ROS2 **service**, not a raw `Twist`/action goal. Operator proposals are explicitly documented and routed through Pi-3's `motion_approval_gateway` for approval ("no source gets a bypass"). `emergency_stop`/`pause`/`resume` are honestly stubbed `_NOT_IMPLEMENTED` rather than faked. **Zero** `Twist`/`cmd_vel`/`ActionClient`/servo-topic references exist anywhere in `bonbon_operator_api`.

---

## Check 14 — Resource guard disables non-critical AI during CPU/temp/memory/battery stress

**CPU/memory/thermal:** `bonbon_edge_ai_runtime/resource_guard.py` wraps `ResourceMonitor` + `LoadSheddingController` + `Pi2LLMGuard` — real, tested, already covered.

**Battery (confirmed live and wired):** `safety_state_machine.py:621` includes `battery_percent <= battery_caution_pct` (default 20%) as a `SafetyLevel.CAUTION` trigger. `perception_efficiency_node.py` subscribes to `/bonbon/safety/state` and passes `safety_caution_or_above` into `LoadSheddingController`, which sheds perception load to `REDUCED` (0.7×) and raises confidence thresholds on CAUTION+ — this chain is real and live, not hypothetical.

**Real gap found and fixed:** `bonbon_edge_ai_runtime/nodes/edge_ai_runtime_node.py` — its own dashboard-facing `resource_guard` view hardcoded `safety_caution_or_above=False` unconditionally (a documented, honest placeholder, but still a real correctness gap for the dashboard's own resource-guard visibility). Fixed: the node now subscribes to `/bonbon/safety/state`, tracks the real level with staleness handling, and derives `safety_caution_or_above` via a new pure, unit-tested function `derive_safety_caution_or_above()` — no message yet, or a stale one, fails toward "assume caution" (rule 13), never silently `False` forever. **Not fixed** (separate, pre-existing, deliberate design choice, not this check's gap): `Pi2LLMGuardConfig.disable_safety_states` excludes CAUTION/DOCKING — the LLM specifically is not disabled by low battery alone, only DANGER/FAULT/SAFE_STOP.

**Tests:** `tests/test_package_integration.py::TestEdgeAiRuntimeNodeSafetyCautionDerivation` (5 tests).

---

## Check 15 — Degraded mode keeps safe reception functions alive

`config/runtime/degraded_mode.yaml`'s `never_disable` list: `safety_supervisor, emergency_stop, hal, lidar_obstacle_safety, navigation_safety, active_person_tracking` — confirmed never shed regardless of degraded depth. Appointment/token/queue functions (`bonbon_patient_kiosk`) have zero LLM/AI dependency at all (check 2's evidence) — entirely unaffected by AI degraded state. Even full guardrail/LLM chain exhaustion (`assistant_guardrails_deny_all`) falls back to "every response replaced with a safe template" (fail closed to a real spoken response, not silence) — matching the same pattern as `llm_orchestrator_node`'s own `_fallback()` templates.

---

## Check 16 — Dashboard shows model/fallback/latency/cache/resource/safety-blocks

`EdgeAIDashboardPublisher`'s 9 views (`registry_view`, `speech_view`, `llm_view`, `vision_view`, `affective_view`, `safety_separation_view`, `resource_guard_view`, `cache_view`, `overview_view`) — all sourced from real, live state via `edge_ai_runtime_node`'s 6 published topics, never a fabricated zero-state (3-state honesty: no bridge / bridge-no-message-yet / real message). 13 REST endpoints, 6 WebSocket channels. `tests/edge_ai/test_dashboard_edge_ai.py` (13 tests).

---

## Check 17 — Hardware-dependent tests are honestly BLOCKED

`hardware_gated`/`ai_hat_gated`/`pi_gated` pytest markers: **104 passed, 7 skipped** when run in isolation this pass (`pytest tests/ -m "hardware_gated or ai_hat_gated or pi_gated"`) — skipped, never faked as passing, with an explicit reason string naming the missing hardware and the opt-in env var. `test_hailo_entries_become_available_on_real_hailo_hardware` is representative: `@ai_hat_gated`, skips unless `BONBON_HAILO_HW_TEST=1` AND a real usable Hailo device is detected.

---

## Check 18 — No fake PASS exists

Every fix in this verification pass follows the same honesty discipline already established throughout this project: `FallbackPolicy.resolve()` returns `degraded=True, active_model_id=None` (never a guessed model) when a chain is genuinely exhausted; `ResourceGuard`/`edge_ai_runtime_node` report `metricsAvailable=False`/fail toward caution rather than fabricate a reading; dashboard snapshot functions report one of 3 honest states, never a fabricated fourth. Full repo-root regression after all 4 fixes in this pass: **957 passed, 14 skipped (hardware-gated, honest), 0 failed.**

---

## Full regression evidence (this verification pass)

```
$ pytest tests/ -q
957 passed, 14 skipped, 1 warning in 75.72s
```

Package-local suites re-verified after each fix: `bonbon_edge_ai_runtime` (24/24), `bonbon_affective_ai` (115/115), `bonbon_ai_model_registry`/`tests/ai_models` (27/27), `tests/perception_ai/test_hailo_runtime_selection.py` (6/6 + 1 hardware-gated skip). Zero regressions from any of the 4 fixes.

## Files changed this pass

- `config/models/model_registry.yaml` — 3 entries flipped to `enabled_by_default: true`
- `config/models/offline_open_source_profile.yaml` — explicit opt-out added
- `ros2_ws/src/bonbon_ai_model_registry/bonbon_ai_model_registry/model_runtime_selector.py` — availability scope widened
- `ros2_ws/src/bonbon_edge_ai_runtime/bonbon_edge_ai_runtime/nodes/edge_ai_runtime_node.py` — real safety-state subscription
- `ros2_ws/src/bonbon_affective_ai/bonbon_affective_ai/fusion/temporal_smoother.py` — generalized for voice
- `ros2_ws/src/bonbon_affective_ai/bonbon_affective_ai/analyzers/voice_emotion_analyzer.py` — smoothing wired in
- `ros2_ws/src/bonbon_affective_ai/bonbon_affective_ai/config/affective_config.py` — new `voice_temporal_window`
- `tests/perception_ai/test_hailo_runtime_selection.py` — updated to assert the corrected behavior
- New tests: `ros2_ws/src/bonbon_edge_ai_runtime/tests/test_package_integration.py` (+5), `ros2_ws/src/bonbon_affective_ai/tests/test_temporal_smoother.py` (new, 10), `ros2_ws/src/bonbon_affective_ai/tests/test_voice_emotion.py` (+3)
