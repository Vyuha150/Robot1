# BonBon Efficiency Upgrade — Compliance Audit & Report

**Audit date:** 2026-06-30
**Scope:** Verifies the BonBon efficiency upgrade (`bonbon_perception_efficiency`,
`bonbon_data_feedback`, plus runtime-optimization changes to
`bonbon_affective_ai`, `bonbon_llm`, `bonbon_vision`, `bonbon_multi_person_tracker`,
`bonbon_speaker_intelligence`, `bonbon_human_state_fusion`, `bonbon_safety`)
against the final strategy:

```
Pretrained models + real environment data + failure-case data
+ temporal smoothing + active-person focus + event-based processing
+ compute budget manager + privacy-safe feedback loop
+ proper evaluation metrics
```

This audit was evidence-based: every claim below was verified by reading the
actual source (grep + read), not recalled from memory of having built it.
Seven gaps were found and fixed in the course of this audit; they are marked
**FIXED (this audit)** below. Two items were initially miscategorized as gaps
and corrected after closer reading; that correction is documented in full
under item 4, since claiming a false gap is itself worth being honest about.

---

## Part 1 — The 9 strategy items

### 1. Pretrained models, not retrained blindly

1. **Where:** `bonbon_vision` (YOLO/MediaPipe-style detectors with a
   `MockDetector` fallback), `bonbon_affective_ai` (DeepFace/InsightFace-style
   face/voice backends), `bonbon_speaker_intelligence` (diarization backend).
   `bonbon_data_feedback` exports labeled data for human-initiated retraining
   — it never calls `.fit()`/`.train()` itself anywhere in the codebase
   (verified: `grep -rln "retrain\|\.fit(\|\.train("` across
   `bonbon_data_feedback`, `bonbon_vision`, `bonbon_affective_ai` returns only
   docstring/README mentions of the *concept* of retraining, never an actual
   call).
2. **Module:** Each perception package owns its own pretrained backend; no
   shared "model manager."
3. **Topics/services:** N/A — this is a build-time/deployment-time property,
   not a runtime interface.
4. **Config:** Per-package model-path/backend-selection parameters (e.g.
   `bonbon_affective_ai`'s `face_backend`/`voice_backend` config).
5. **Tests:** N/A directly; indirectly covered by every package's mock-mode
   tests (every perception node must work in simulation/mock mode per the
   project's hard rule, verified throughout each package's test suite).
6. **Failure cases handled:** A backend that fails to load falls back to a
   safe degraded/mock mode rather than crashing the node (see each
   `_warmup_backends`/equivalent).
7. **Performance metric:** N/A — model selection isn't itself a measured
   runtime metric.
8. **Privacy/safety:** N/A — this is a model-lifecycle property, not a data
   handling one.

**Status: confirmed, no gap.**

### 2. Real environment data collected safely (hospitals, hotels, offices, homes, universities)

1. **Where:** `bonbon_data_feedback`'s `PrivacySafeDataPolicy` +
   `FailureCaseLogger`/`HardNegativeCollector`.
2. **Module:** `bonbon_data_feedback/core/privacy_safe_data_policy.py`.
3. **Topics/services:** `~/report_failure_case`
   (`bonbon_srvs/ReportFailureCase`), automatic logging via
   `/bonbon/gesture/events`.
4. **Config:** `debug_mode_enabled` (must be `false` in production),
   per-category `retention_days_by_category`.
5. **Tests:** 13 tests in `test_privacy_safe_data_policy.py`.
6. **Failure cases handled:** Forbidden context keys (raw biometric payload)
   are stripped *unconditionally*, even in debug mode — verified by
   `test_forbidden_keys_stripped_EVEN_in_debug_mode`.
7. **Performance metric:** N/A.
8. **Privacy/safety:** This *is* the privacy/safety control. The design is
   deliberately **venue-agnostic** rather than hospital/hotel/office-specific:
   the retention/sanitization rules apply uniformly regardless of deployment
   site, which is the correct generalization — building separate code paths
   per venue type would be over-engineering for a property (data
   sensitivity) that doesn't actually vary by venue in a way the system can
   observe at runtime. The category-based retention (face: 30 days, object:
   90 days) is what actually varies, and that's already config-driven per
   deployment.

**Status: confirmed, no gap.** "Safely across venue types" is satisfied by a
venue-agnostic privacy policy, not per-venue special-casing.

### 3. Failure-case data logged separately

1. **Where:** `bonbon_data_feedback` — an entire dedicated package.
2. **Module:** `FeedbackStore` (repository), `FailureCaseLogger`,
   `HardNegativeCollector`.
3. **Topics/services:** `~/report_failure_case`, automatic gesture-confidence
   logging via `/bonbon/gesture/events` + `/bonbon/perception_efficiency/policy`.
4. **Config:** `db_path` (separate database file from `bonbon_data_stores`'
   operational data), `hard_negative_confidence_threshold`.
5. **Tests:** 16 tests in `test_feedback_store.py`, 13 in
   `test_failure_case_logger.py`, 9 in `test_hard_negative_collector.py`.
6. **Failure cases handled:** Honest low-confidence misses (`FailureCaseLogger`)
   vs. confident-but-wrong cases (`HardNegativeCollector`) are deliberately
   distinguished — the latter is the more valuable retraining signal.
7. **Performance metric:** `count_failure_cases()`, `diarization_ambiguous_rate`
   and `id_switch_count` (see item 9) feed into this same failure-case
   philosophy elsewhere in the codebase.
8. **Privacy/safety:** Separate database file (not `bonbon_data_stores`'
   operational tables) specifically *because* of different retention rules —
   reuses `SQLiteConnection`/`SchemaMigrator` directly rather than a second
   ad-hoc DB layer (no duplication).

**Status: confirmed, no gap.**

### 4. Temporal smoothing — object detection, gesture, emotion, person tracking, speaker identity, spatial state

1. **Where (per signal):**
   - **Gesture:** `bonbon_gesture/logic/temporal_smoother.py` (pre-existing,
     label-stability based).
   - **Emotion:** `bonbon_affective_ai/fusion/temporal_smoother.py`
     (pre-existing).
   - **Person tracking (lifecycle/presence):**
     `bonbon_multi_person_tracker/core/lifecycle_state_machine.py` —
     `confirmation_hits`/`loss_grace_sec` hysteresis (a single missed frame
     never causes a "left" transition).
   - **Object detection (permanence):**
     `bonbon_object_intelligence/core/object_permanence_tracker.py` —
     `occlusion_grace_sec`/`memory_grace_sec` (an occluded object isn't
     immediately "gone").
   - **Speaker identity:** `bonbon_speaker_intelligence/core/speaker_identity_manager.py`
     — `recency_window_sec` (a speaker who pauses briefly is still the same
     identity, not a new one).
   - **Spatial state (corridor blockage):**
     `bonbon_spatial/core/blockage_detector.py` — `persistence_sec`
     (sustained occupancy required before declaring a blockage; clears
     instantly when the corridor is clear, which is the correct asymmetry —
     a false-positive blockage should require confirmation, but telling
     navigation "you may proceed" should never be delayed).
   - **Generic primitive:** `bonbon_perception_efficiency/core/temporal_smoothing_manager.py`
     — a reusable majority-vote stabilizer for any *future* signal that
     doesn't already have its own (none of the six above needed it, since
     each already had a fit-for-purpose mechanism).
2. **Module:** Listed per-signal above; no central "smoothing service" — each
   lives where its signal is produced, which is correct (smoothing logic
   needs domain-specific tuning, e.g. occlusion grace differs from
   speaker-recency window).
3. **Topics/services:** N/A — internal to each producing node.
4. **Config:** `confirmation_hits`, `loss_grace_sec`, `occlusion_grace_sec`,
   `memory_grace_sec`, `recency_window_sec`, `persistence_sec` — all
   per-package ROS2 parameters.
5. **Tests:** Covered by each owning package's existing test suite (not
   re-verified here since none of these six needed code changes).
6. **Failure cases handled:** Single-frame sensor noise causing spurious
   state flips (false "person left," false "object gone," false "new
   speaker," false "corridor blocked").
7. **Performance metric:** `id_switch_count` (person tracking, **added this
   audit**, see item 9), `diarization_ambiguous_rate` (speaker, **added this
   audit**).
8. **Privacy/safety:** N/A directly.

**Self-correction recorded here for transparency:** this audit initially
(incorrectly) concluded "spatial state has no temporal smoothing" based on a
keyword grep that searched for `smooth`/`alpha`/`hysteresis`/`kalman` and
missed `BlockageDetector`'s `persistence_sec` mechanism, which uses different
terminology for the same concept. Re-reading `blockage_detector.py`'s actual
`update()` body before implementing anything caught this. **No code was
changed for this item** — the original implementation was already correct.
This is recorded because an audit that silently "fixes" a non-gap would have
produced unnecessary, undocumented churn for no reason; catching it before
writing code is the success case the project's "audit first" rule exists for.

**Status: confirmed, no gap, after self-correction.**

### 5. Active-person focus — reduce background processing, prioritize active speaker

1. **Where:** `bonbon_perception_efficiency/core/active_person_focus_manager.py`
   (the weight computation) + `bonbon_human_state_fusion/core/focus_publish_gate.py`
   (**FIXED this audit** — the actual consumer).
2. **Module:** `ActivePersonFocusManager` (weight: focus=1.0, new
   arrival=0.8, background=0.3) + `FocusPublishGate` (applies the weight by
   throttling `HumanState` publish cadence for background people to once
   every `background_publish_every_n_cycles`, default 3).
3. **Topics/services:** Weight published as part of
   `/bonbon/perception_efficiency/budget` (`PerceptionBudget.msg`); consumed
   internally by `human_state_fusion_node`'s `_run_cycle`.
4. **Config:** `bonbon_human_state_fusion`'s
   `background_publish_every_n_cycles` (default 3).
5. **Tests:** 6 tests for `ActivePersonFocusManager` (pre-existing), 9 new
   tests for `FocusPublishGate` (focus/new-arrival/background/left-scene
   handling, throttle reset, counter pruning, no-focus-person edge case).
6. **Failure cases handled:** `left_scene` departures are *never* throttled
   (a terminal, one-time event must never be silently dropped just because
   that person was previously in the background) — verified by
   `test_left_scene_always_published_even_if_was_background`.
7. **Performance metric:** Reduced `HumanState` publish volume for
   background people — directly observable as a lower per-person publish
   rate in `/bonbon/human/state` traffic.
8. **Privacy/safety:** N/A directly — this changes publish *cadence*, never
   what data is in a published message.

**Status: FIXED (this audit).** Before this fix, `ActivePersonFocusManager`
computed a weight that *nothing read* — `bonbon_perception_efficiency`'s own
README explicitly documented this as an "honest limitation." `vision_node`
and `gesture_node` cannot selectively skip people at the inference level
(MediaPipe-style multi-person detection processes the whole frame in one
batched call — there's no per-person "don't bother" hook to wire into).
`human_state_fusion_node` is the architecturally correct consumer instead: it
already iterates every tracked person every cycle, so reducing *publish*
cadence for background people is the same "reduce rate, don't redo
detection" pattern `FrameSamplingManager` already uses for `bonbon_vision`,
just applied per-person instead of per-consumer.

### 6. Event-based processing prevents unnecessary continuous inference

1. **Where:** `bonbon_affective_ai`'s audio buffer (triggers voice analysis
   only when `voice_segment_min_sec` of audio has accumulated, not on a
   fixed timer) and transcript callback (triggers text analysis only when a
   `SpeechCommand` actually arrives). `bonbon_data_feedback`'s automatic
   logging triggers only on a `GestureEvent` below the confidence floor, not
   on a poll.
2. **Module:** `bonbon_affective_ai/nodes/affective_ai_node.py`
   (`_cb_audio`/`_cb_transcript`).
3. **Topics/services:** `/bonbon/speech/audio` (event-triggers voice
   analysis), `/bonbon/speech/transcript` (event-triggers text analysis).
4. **Config:** `voice_segment_min_sec`.
5. **Tests:** Covered by `bonbon_affective_ai`'s existing test suite.
6. **Failure cases handled:** Backpressure when events arrive faster than
   they can be processed — see item 13 (`BoundedInferenceQueue`).
7. **Performance metric:** Inference call count vs. wall-clock time (lower
   for event-triggered vs. fixed-timer polling, by construction).
8. **Privacy/safety:** N/A directly.

**Honest scope note:** `bonbon_vision`'s frame processing is
timer-driven at a fixed rate (a camera inherently produces a continuous
frame stream — there is no "event" to wait for at the frame-capture layer),
but the rate itself is now dynamically throttled by
`bonbon_perception_efficiency`'s `FrameSamplingManager`/load shedding (item
7), which is the correct mitigation for a continuous-by-nature sensor: you
can't make camera frames "event-based," but you can make *how often you
process them* responsive to load.

**Status: confirmed for genuinely event-driven signals (audio/transcript);
continuous signals (camera) are correctly handled via dynamic rate control
instead, which is the right tool for that signal type.**

### 7. Compute budget manager — CPU, memory, or thermal overload

1. **Where:** `bonbon_perception_efficiency/core/load_shedding_controller.py`
   + `degraded_mode_manager.py` + `frame_sampling_manager.py`.
2. **Module:** `LoadSheddingController` (hysteresis-gated level:
   normal→reduced→minimal→critical), driven by `PerceptionBudgetManager`.
3. **Topics/services:** Subscribes `/bonbon/system/resource_usage`
   (`ResourceUsage`, from `bonbon_safety`'s `ResourceMonitor`) and
   `/bonbon/temperature/readings` (`ThermalReadings`, **FIXED this audit** —
   from `bonbon_hal`). Publishes `/bonbon/perception_efficiency/budget`.
4. **Config:** `hysteresis_cycles` (de-escalation delay), `cpu_temp_caution_c`
   (default 75.0°C, **added this audit**).
5. **Tests:** 14 tests in `test_load_shedding_controller.py` (9 pre-existing
   + 5 new thermal tests), 2 new thermal tests in
   `test_perception_budget_manager.py`.
6. **Failure cases handled:** CPU overload, memory pressure, thermal
   overload, and combinations (e.g. thermal + CPU together escalate to
   CRITICAL, same severity as CPU+memory together) — escalation is always
   immediate, de-escalation requires sustained recovery (no flapping).
7. **Performance metric:** `LoadSheddingDecision.scale` (0.15–1.0 processing
   multiplier), published as part of `PerceptionBudget.msg`.
8. **Privacy/safety:** The 75°C `cpu_temp_caution_c` threshold is not
   arbitrary — it mirrors `bonbon_safety`'s `SafetyStateMachine`
   `cpu_temp_caution_c` default *exactly*, so perception load shedding acts
   **preventively, strictly before** the Safety Supervisor's own
   `cpu_temp_fault_c` (90°C) threshold would force a SAFE_STOP. This is a
   deliberate safety-adjacent design choice, not a coincidence.

**Status: FIXED (this audit).** Before this fix, `LoadSheddingController` had
CPU and memory inputs but no thermal input at all, despite `ThermalReadings`
already being published by `bonbon_hal` and consumed by `bonbon_safety` — the
data existed, it just wasn't reaching the perception-efficiency layer. The
fix reuses the existing publication (no second temperature-sampling
pipeline) rather than adding `psutil`-based sensor reading to
`ResourceMonitor`, which would have duplicated `bonbon_hal`'s thermal_node.

### 8. Privacy-safe feedback loop — no raw face/audio by default

1. **Where:** `bonbon_data_feedback/core/privacy_safe_data_policy.py`.
2. **Module:** `PrivacySafeDataPolicy.is_raw_snapshot_allowed()` /
   `.sanitize_context()`.
3. **Topics/services:** Gates `raw_snapshot_path` in `FailureCaseLogger.log()`
   and the `~/report_failure_case` service.
4. **Config:** `debug_mode_enabled` (default `false`) — the *only* way raw
   snapshot storage can ever be enabled, and it's an explicit launch
   parameter, never inferred or defaulted on.
5. **Tests:** 13 tests, including `test_forbidden_keys_stripped_EVEN_in_debug_mode`
   — the strongest test in the suite, verifying that even with debug mode
   on, raw payload (as opposed to a file-path reference) can never enter the
   general context dict.
6. **Failure cases handled:** A caller accidentally passing raw bytes in a
   "safe" context dict — caught by `_FORBIDDEN_CONTEXT_KEYS` regardless of
   debug mode.
7. **Performance metric:** N/A — this is a binary safety property, not a
   graduated metric.
8. **Privacy/safety:** This *is* the privacy/safety control, doubled: (1)
   `is_raw_snapshot_allowed()` gates the *path reference*, (2)
   `sanitize_context()` strips raw *payload* unconditionally, as defense in
   depth against the first gate being misused.

**Status: confirmed, no gap.**

### 9. Proper evaluation metrics — accuracy, latency, false triggers, ID switches, diarization errors, dropped frames, CPU, memory, safety events

1. **Where (per metric):**
   - **Accuracy:** `bonbon_data_feedback/core/model_evaluation_store.py` —
     `record_evaluation()`/`compare()` across model versions.
   - **Latency:** Every node's `ModuleHealth.latency_ms`, aggregated by
     `bonbon_perception_efficiency/core/perception_metrics_aggregator.py`.
   - **False triggers:** `bonbon_gesture`'s confidence threshold +
     `bonbon_data_feedback`'s automatic low-confidence logging (the system's
     own self-reported false-trigger candidates).
   - **ID switches:** `bonbon_multi_person_tracker/core/multi_person_scene_manager.py`
     — `id_switch_count` (**FIXED this audit**).
   - **Diarization errors:** `bonbon_speaker_intelligence/core/speaker_turn_builder.py`
     — `diarization_ambiguous_count`/`diarization_ambiguous_rate` (**FIXED
     this audit**).
   - **Dropped frames:** `bonbon_perception_efficiency/core/stale_frame_dropper.py`
     + `bounded_inference_queue.py`'s `dropped_count`.
   - **CPU/memory:** `bonbon_safety`'s `ResourceMonitor`, published as
     `ResourceUsage`.
   - **Safety events:** `bonbon_safety`'s existing `SafetyEvent`/`SafetyState`
     publication (pre-existing, untouched).
2. **Module:** Listed per-metric above.
3. **Topics/services:** `/bonbon/perception_efficiency/metrics`
   (aggregated), `/bonbon/system/resource_usage`, `/bonbon/safety/state`,
   plus each owning node's own `ModuleHealth` status text (where the two new
   metrics are surfaced: `"nominal (id_switches=N)"`,
   `"nominal (diarization_ambiguous_rate=0.XX)"`).
4. **Config:** N/A for the metrics themselves — they're always-on counters.
5. **Tests:** 5 new tests for `id_switch_count`
   (`test_multi_person_scene_manager.py`), 5 new tests for
   `diarization_ambiguous_count`/`rate` (`test_speaker_turn_builder.py`).
6. **Failure cases handled:** ID switches specifically measure raw-tracker
   churn caught and corrected via re-identification (Pass 3 of
   `MultiPersonSceneManager.update()`), distinguished from genuine
   reappearance-after-loss (Pass 2), verified by a dedicated test
   (`test_reappearance_after_real_loss_does_not_count_as_id_switch`).
   Diarization ambiguity specifically measures overlapping-speech utterances
   — the system's own honest self-assessed signal of diarization difficulty,
   since no ground truth is available at runtime to compute a true
   Diarization Error Rate.
7. **Performance metric:** These items *are* the performance metrics.
8. **Privacy/safety:** N/A — these are operational counters, not data with
   privacy implications.

**Status: FIXED (this audit), 2 of 8 sub-metrics.** ID switches and
diarization errors were named explicitly in the brief's evaluation-metrics
list but had no counter anywhere in the codebase before this audit. The
other 6 sub-metrics (accuracy, latency, false triggers, dropped frames,
CPU/memory, safety events) were already present and required no change.

---

## Part 2 — The 15 specific checks

| # | Check | Status |
|---|---|---|
| 1 | Pretrained models used as base, not retrained blindly | ✅ Confirmed |
| 2 | Real environment data collected safely across venues | ✅ Confirmed (venue-agnostic policy is the correct design) |
| 3 | Failure-case data logged separately | ✅ Confirmed |
| 4 | Temporal smoothing: object/gesture/emotion/person/speaker/spatial | ✅ Confirmed (spatial state initially miscategorized as a gap, self-corrected) |
| 5 | Active-person focus reduces background processing | 🔧 **FIXED** — `FocusPublishGate` added |
| 6 | Event-based processing prevents unnecessary continuous inference | ✅ Confirmed (camera frames correctly use dynamic rate control instead, since they're inherently continuous) |
| 7 | Compute budget manager reduces FPS/models under CPU/memory/thermal overload | 🔧 **FIXED** — thermal wired into `LoadSheddingController` |
| 8 | Privacy-safe feedback loop avoids raw storage by default | ✅ Confirmed |
| 9 | Evaluation metrics: accuracy/latency/false-triggers/ID-switches/diarization/dropped-frames/CPU/memory/safety | 🔧 **FIXED** — ID-switch + diarization-error counters added |
| 10 | Safety Supervisor remains highest priority under all degraded modes | ✅ Confirmed — see below |
| 11 | LLM calls reduced, never directly control robot action | ✅ Confirmed — see below |
| 12 | RAG calls cached, only triggered when needed | 🔧 **FIXED** — cache check moved before RAG retrieval |
| 13 | Database writes batched and non-blocking | 🔧 **FIXED** — automatic write path made async |
| 14 | Degraded mode keeps safety/navigation/active-person-tracking alive before optional AI | ✅ Confirmed — see below |
| 15 | No redundant camera/audio/database/behavior pipelines | ✅ Confirmed throughout |

**Check 10 detail (Safety Supervisor highest priority):** Verified by
construction, not just by absence of a counter-example.
`bonbon_perception_efficiency` only ever *observes* `/bonbon/safety/state`
(`SafetyState`) — it has no subscription to, or write path into, anything
`bonbon_safety` owns. `DegradedModeManager.update()` treats
`safety_fault_or_above=True` as an *immediate* trigger (no sustained-pressure
delay, unlike load-based degradation), meaning perception degrades in
lockstep with safety the instant a FAULT/SAFE_STOP occurs, never the reverse.
No code anywhere in this engagement touches `bonbon_safety`'s own
publish/subscribe surface except to *read* `SafetyState` and
`ResourceUsage`/`ThermalReadings` (which `bonbon_safety` already published
before this engagement, for `ResourceUsage`; `ThermalReadings` is owned by
`bonbon_hal`).

**Check 11 detail (LLM never directly controls actuation):** Verified
directly in `llm_orchestrator_node.py`'s own docstring and code path: *"LLM
output NEVER reaches cmd_vel, nav2, or GPIO directly."* Any `behavior_class`
resolved from an intent passes through `CommandAuthorizer.authorize(...)`
against the live `SafetyState` snapshot before `_dispatch_behavior` is ever
called — the LLM can *request* a behavior, never execute one. This was
pre-existing and unmodified by this engagement; this audit's RAG-caching fix
(check 12) reduces *call volume* but does not touch this authorization gate.

**Check 14 detail (degraded mode priority order):** Verified by scope, not
just by absence: `bonbon_perception_efficiency`'s `LoadSheddingController`/
`DegradedModeManager`/`FrameSamplingManager` only ever throttle *perception*
consumers (`vision`, `gesture` sample rates; `HumanState` publish cadence for
background people). None of these has a subscription to, publisher for, or
parameter touching `bonbon_safety`, `bonbon_navigation`, or active-person
*tracking* itself (`bonbon_multi_person_tracker`'s own update cycle is
untouched — only `bonbon_human_state_fusion`'s downstream *publish* cadence
for background people is throttled, never tracking itself, and never the
focus person's publish cadence). The packages this audit touches are
strictly "optional AI" in the brief's own terms.

---

## Part 3 — Gaps found and fixed (summary)

| Gap | Fix | Commit |
|---|---|---|
| RAG retrieval ran on every cache hit, not just on a miss | Cache check moved before RAG retrieval, keyed on `(question, scene+safety context)` excluding RAG results | `fix(bonbon_llm): cache check now actually skips RAG retrieval...` |
| `LoadSheddingController` had no thermal input | Subscribed to existing `ThermalReadings`; added `thermal_overloaded` param, mirroring `bonbon_safety`'s `cpu_temp_caution_c` (75°C) | `fix(bonbon_perception_efficiency): wire thermal overload into load shedding` |
| No person-tracking ID-switch metric | `MultiPersonSceneManager.id_switch_count`, counting Pass-3 churn-merge re-identifications | `feat(bonbon_multi_person_tracker): person-tracking ID-switch metric` |
| No speaker diarization-error metric | `SpeakerTurnBuilder.diarization_ambiguous_count`/`rate`, counting overlapping-segment utterances | `feat(bonbon_speaker_intelligence): speaker diarization-error metric` |
| `data_feedback_node`'s automatic write blocked the ROS callback thread | `ThreadPoolExecutor` + `BoundedInferenceQueue` gate in front of the write, mirroring `bonbon_affective_ai`'s pattern | `fix(bonbon_data_feedback): make the automatic failure-case write path non-blocking` |
| Active-person focus weight had no consumer | `FocusPublishGate` in `bonbon_human_state_fusion`, throttling background-people `HumanState` publish cadence | `feat(bonbon_human_state_fusion): FocusPublishGate -- the real consumer of active-person focus` |
| (Initially suspected) spatial state had no temporal smoothing | **Self-corrected, no fix needed** — `BlockageDetector.persistence_sec` already implements this; the original audit grep missed the terminology | N/A (documented above) |

---

## Part 4 — Final efficiency compliance report

### 1. Final architecture map

```
                          ┌─────────────────────────┐
                          │   bonbon_safety          │
                          │  ResourceMonitor          │
                          │  SafetyStateMachine        │
                          └─────────┬────────┬────────┘
                     ResourceUsage  │        │ SafetyState
                                    ▼        ▼
┌──────────────┐   ThermalReadings ┌──────────────────────────┐
│  bonbon_hal   ├──────────────────►  bonbon_perception_       │
└──────────────┘                   │  efficiency               │
                                    │  (LoadSheddingController,  │
┌──────────────────────┐ PersonTrack│  DegradedModeManager,      │
│ bonbon_multi_person_  ├───────────►  FrameSamplingManager,     │
│ tracker (+id_switch_  │           │  ConfidencePolicyManager,  │
│ count metric)         │           │  ActivePersonFocusManager, │
└──────────────────────┘           │  PerceptionMetricsAggreg.) │
                                    └─────────┬─────────────────┘
┌──────────────────────┐  ModuleHealth        │ PerceptionPolicy/Budget/
│ every perception node ├──────────────────────┤ DegradedMode/Metrics
└──────────────────────┘                      ▼
                                    ┌──────────────────────────┐
┌──────────────────────┐ HumanState │  bonbon_human_state_      │
│ bonbon_human_state_   ├───────────►  fusion                    │
│ fusion (+FocusPublish-│  (throttled│  (consumes budget's focus │
│ Gate)                 │  for bg)   │  weight via FocusPublishGate)│
└──────────────────────┘            └──────────────────────────┘

┌──────────────────────┐ GestureEvent
│ bonbon_gesture         ├──────────┐
└──────────────────────┘           ▼
                          ┌──────────────────────────┐
                          │  bonbon_data_feedback      │
                          │  (FailureCaseLogger,       │
                          │   HardNegativeCollector,    │
                          │   PrivacySafeDataPolicy,    │
                          │   non-blocking write path)  │
                          └──────────────────────────┘

┌──────────────────────┐ ResponseCache (RAG+LLM both skipped on hit)
│ bonbon_llm             │
│ (CommandAuthorizer gate│ → never reaches cmd_vel/nav2/GPIO directly
└──────────────────────┘

┌──────────────────────┐
│ bonbon_speaker_        │ (+diarization_ambiguous_rate metric)
│ intelligence           │
└──────────────────────┘
```

### 2. Modules changed (this audit)

- `bonbon_llm`: `llm_orchestrator_node.py`, `core/response_cache.py`
- `bonbon_perception_efficiency`: `load_shedding_controller.py`,
  `perception_budget_manager.py`, `nodes/perception_efficiency_node.py`,
  `active_person_focus_manager.py` (docstring only)
- `bonbon_multi_person_tracker`: `multi_person_scene_manager.py`,
  `nodes/multi_person_tracker_node.py`
- `bonbon_speaker_intelligence`: `speaker_turn_builder.py`,
  `nodes/speaker_intelligence_node.py`
- `bonbon_data_feedback`: `nodes/data_feedback_node.py`, `package.xml`,
  `pytest.ini`
- `bonbon_human_state_fusion`: new `core/focus_publish_gate.py`,
  `nodes/human_state_fusion_node.py`, `package.xml`, `pytest.ini`, config

### 3. Modules NOT touched (verified correct as-is, no change needed)

- `bonbon_safety` (SafetyStateMachine, ThreatAssessor, ResourceMonitor) —
  remains the sole source of truth for safety state; nothing in this audit
  reads from or writes to it except the pre-existing `ResourceUsage`/
  `SafetyState` subscriptions.
- `bonbon_gesture`, `bonbon_affective_ai`'s temporal smoothers — already
  correct, confirmed by reading, not changed.
- `bonbon_object_intelligence`'s `ObjectPermanenceTracker` — already correct.
- `bonbon_spatial`'s `BlockageDetector` — already correct (see the
  self-correction in item 4).
- `bonbon_vision`, `bonbon_navigation`, `bonbon_actuation` — out of this
  audit's scope; no claim in the brief implicated them beyond what was
  already fixed in the earlier runtime-optimization phase (dynamic FPS,
  bounded queues — see `EFFICIENCY_ARCHITECTURE.md`).

### 4. Redundancies avoided

- Thermal: reused `bonbon_hal`'s existing `ThermalReadings` publication
  rather than adding a second `psutil`-based temperature sampler to
  `ResourceMonitor`.
- Active-person focus: reused `select_focus_person`
  (`bonbon_behavior_engine`) and `ActivePersonFocusManager`
  (`bonbon_perception_efficiency`) directly in `FocusPublishGate` rather than
  re-deriving either's priority logic a third time.
- Non-blocking writes: reused `BoundedInferenceQueue`
  (`bonbon_perception_efficiency`) in `bonbon_data_feedback`, the same
  backpressure primitive already used in `bonbon_affective_ai`.
- No new database connection layer — `bonbon_data_feedback` reuses
  `SQLiteConnection`/`SchemaMigrator` from `bonbon_data_stores`.
- No new camera, microphone, or detection pipeline anywhere in this audit.

### 5. Performance improvements expected

- RAG fix: eliminates RAG retrieval entirely on a cache hit (previously
  only the LLM call was skipped) — measurable as reduced RAG-backend call
  count for repeated questions within the 30s cache TTL.
- Thermal fix: perception throughput now reduces *before* the Safety
  Supervisor's 90°C fault threshold is reached, reducing the likelihood of
  thermally-triggered SAFE_STOPs caused by sustained perception load.
- Active-person focus fix: reduces `HumanState` publish volume (and
  downstream consumer processing of it) for background people by a factor
  of `background_publish_every_n_cycles` (default 3× reduction).
- Non-blocking writes: removes SQLite write latency from the gesture-event
  callback's critical path entirely.

### 6. Remaining bottlenecks (honestly scoped, not fixed in this audit)

- `bonbon_vision`'s frame processing is fundamentally timer/poll-driven
  (cameras are continuous sensors) — dynamic-rate mitigation exists, but
  "event-based" in the literal sense isn't achievable for this signal type.
- `FocusPublishGate` throttles *publish cadence*, not the underlying fusion
  *computation* (`HumanStateFusionEngine.build_all()` still computes every
  tracked person every cycle) — a further optimization would skip
  computation, not just publication, for background people, but that risks
  staleness if a background person suddenly becomes the focus mid-window.
- `PerceptionPolicy`/`PerceptionBudget` remain advisory-only for every
  consumer except `FocusPublishGate` — `ConfidencePolicyManager`'s
  recommended thresholds and `FrameSamplingManager`'s recommended sample
  rates still have no live-reconfigure path into the nodes they advise.

### 7. Test coverage (this audit)

| Package | New tests | Total tests after audit |
|---|---|---|
| `bonbon_llm` | 4 (`TestProcessIntentCacheSkipsRagAndLlm`) | 257 |
| `bonbon_perception_efficiency` | 7 (thermal) | 77 |
| `bonbon_multi_person_tracker` | 5 (ID switch) | 53 |
| `bonbon_speaker_intelligence` | 5 (diarization) | 43 |
| `bonbon_data_feedback` | 7 (non-blocking write) | 62 |
| `bonbon_human_state_fusion` | 9 (`FocusPublishGate`) | 73 |

All fixes were verified against the **real** method under test (not a
re-implementation) wherever the method was reasonably testable —
`_process_intent`, `_cb_gesture_event`/`_write_gesture_failure_case`, and
`_run_cycle`'s logic (via `FocusPublishGate.select`) were all exercised
directly, not approximated.

### 8. Deployment checklist

- [ ] `debug_mode_enabled` confirmed `false` in every production launch
      config for `bonbon_data_feedback`.
- [ ] `cpu_temp_caution_c` (75°C) confirmed to match the deployed
      `bonbon_safety` `SafetyStateMachine` config if that value is ever
      changed from its default in either package — they must stay in sync
      manually since they are deliberately not cross-imported.
- [ ] `background_publish_every_n_cycles` tuned per deployment if a
      downstream consumer (e.g. an operator dashboard) needs fresher
      background-person state than the default 3-cycle throttle provides.
- [ ] Confirm `colcon build` resolves the new cross-package dependencies
      added this audit: `bonbon_affective_ai`→`bonbon_perception_efficiency`,
      `bonbon_data_feedback`→`bonbon_perception_efficiency`,
      `bonbon_human_state_fusion`→`bonbon_behavior_engine`+`bonbon_perception_efficiency`.
      All were checked for circular dependencies before being added; none
      exist.
- [ ] Run `scripts/test.sh --no-ros2` (full pure-Python gate) and the ROS2
      workspace test job before any production rollout — both were green
      after every commit in this audit.

### 9. Next improvement roadmap

1. Give `ConfidencePolicyManager`'s and `FrameSamplingManager`'s
   recommendations a real consumer, the same way `FocusPublishGate` is now
   the real consumer of `ActivePersonFocusManager` — likely via a small
   live-reconfigure parameter-set call from each advised node on a policy
   change, rather than a one-way advisory topic.
2. Investigate whether `HumanStateFusionEngine.build_all()` can skip
   *computation* (not just publication) for background people without
   risking staleness when someone transitions from background to focus —
   would require a "always recompute, but only sometimes publish" → "mostly
   skip recompute, always recompute on a focus change" redesign.
3. Extend `diarization_ambiguous_rate` and `id_switch_count` into the
   `PerceptionEfficiencyMetrics` aggregate topic, so a single dashboard
   subscription surfaces both alongside CPU/memory/load-level, rather than
   requiring a separate subscription to each owning node's health
   status_text.
4. Consider whether `bonbon_data_feedback`'s `~/report_failure_case`
   service should also gain a queue-based async variant for callers that
   don't need the synchronous `case_id` response (e.g. a fire-and-forget
   reporting mode), while keeping the current synchronous behavior as the
   default for callers that do.
