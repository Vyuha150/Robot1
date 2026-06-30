# BonBon Scenario Families

A **scenario family** is a generator, not a fixed test case: a bounded set of
variables that combine into many concrete scenarios (Phase 2 generates the
actual combinations into `tests/scenarios/generated_scenarios/`). This
document defines the 15 families. Every family below is consumed by exactly
one `tests/production/test_*_scenarios.py` file (Phase 4) and judged by the
Behavior Oracle (Phase 3) — never by a test asserting an isolated module
output in a vacuum.

Risk levels: **CRITICAL** (safety/people can be hurt) · **HIGH** (wrong
behavior in front of a user, no physical hazard) · **MEDIUM** (degraded
quality of service) · **LOW** (operator/observability only).

---

## 1. Boot and Deployment Topology

- **Purpose:** prove the robot always boots into exactly one valid topology (monolithic XOR modular_pi), never a duplicate-safety mix.
- **Risk:** CRITICAL.
- **Modules:** systemd units, `devops/scripts/boot_topology.py`, `bonbon_safety`.
- **Environment variables:** fresh install, upgrade-in-place, power-loss-mid-boot.
- **Human variables:** none (unattended boot).
- **Robot state variables:** monolithic mode, modular_pi mode, mixed/invalid mode, all-services-disabled.
- **Sensor variables:** n/a.
- **AI model variables:** n/a.
- **Expected behavior:** exactly one `safety_supervisor_node`; dependent units wait on `bonbon-safety`.
- **Safety constraints:** zero duplicate safety supervisors; zero "no supervisor" windows once boot completes.
- **Dashboard expectations:** `/validation/scenario-families` shows this family green; `boot_topology.json` reflects the live mode.
- **Pass criteria:** `classify_topology()` returns `MONOLITHIC` or `MODULAR_PI` with `observed_safety_supervisors == 1`.
- **Fail criteria:** `INVALID`, count `!= 1`, or validator exit code `!= 0`.
- **Recovery behavior:** `select_deployment_mode.sh` disables the conflicting set and re-validates; never auto-silences the conflict.
- **Logs required:** `devops/project-status/boot_topology.json`, systemd journal for the affected units.
- **Metrics required:** boot-topology pass rate, mean time-to-valid-topology after a mode switch.
- **CI-safe test strategy:** pure-Python classifier fed synthetic enabled-unit sets (already 12 tests in `devops/tests/test_boot_topology.py`).
- **Simulation strategy:** n/a (systemd has no meaningful simulation; the classifier *is* the testable abstraction).
- **Hardware-gated strategy:** `pi_gated` — live `systemctl is-active` + `ros2 node list` count on a booted Pi.

## 2. Raspberry Pi + AI HAT Runtime

- **Purpose:** prove inference correctly selects/falls back across Hailo → CPU → mock, and never silently reports a fake accelerator.
- **Risk:** HIGH.
- **Modules:** `bonbon_ai_runtime` (`RuntimeSelector`, `HailoRuntime`, `HailoDeviceDetector`).
- **Environment variables:** HAT present/absent, HailoRT installed/missing, `.hef` present/missing/wrong-format.
- **Human variables:** none.
- **Robot state variables:** cold start, warm runtime, runtime crash mid-inference.
- **Sensor variables:** camera frame available/stalled.
- **AI model variables:** model compiled for hailo8 vs hailo8l, ONNX-only model, corrupted `.hef`.
- **Expected behavior:** `auto` mode prefers Hailo when truly available; otherwise falls back to CPU then mock with `fallback_active=True` and a stated `reason`.
- **Safety constraints:** a fallback to mock must never be reported as `is_real_accelerator: true`.
- **Dashboard expectations:** `/ai-runtime/status` always shows the *actual* selected kind.
- **Pass criteria:** selected runtime matches the priority chain given the injected availability; `ai_runtime_bench` exits non-zero on silent mock fallback when Hailo was requested.
- **Fail criteria:** wrong runtime selected, or a fallback misreported as the requested accelerator.
- **Recovery behavior:** fail-open to mock so vision keeps publishing (degraded) rather than crashing the node.
- **Logs required:** `RuntimeHealth` transitions, `InferenceMetricsCollector` rolling stats.
- **Metrics required:** Hailo-availability detection accuracy, fallback-reporting honesty rate, inference latency by runtime kind.
- **CI-safe test strategy:** 27 existing unit tests with injected `ImportProbe`/`CommandRunner`/`infer_factory`.
- **Simulation strategy:** `MockRuntime` stands in for the accelerator end-to-end through `bonbon_vision`.
- **Hardware-gated strategy:** `ai_hat_gated` — real `HailoDeviceDetector().detect()` + real `.hef` inference (`test_hardware_gated.py`).

## 3. Safety and Emergency Stop

- **Purpose:** prove the Safety Supervisor blocks unsafe commands and the E-stop path is independent of AI load.
- **Risk:** CRITICAL.
- **Modules:** `bonbon_safety` (supervisor, watchdog, e-stop node), `bonbon_actuation`.
- **Environment variables:** normal load, full AI load (vision+speech+LLM concurrently), CPU-saturated.
- **Human variables:** person in stop zone, person issues stop-palm/voice "stop", no human present.
- **Robot state variables:** idle, navigating, speaking, docking.
- **Sensor variables:** all-nominal, lidar lost, camera lost.
- **AI model variables:** n/a (E-stop must not depend on AI).
- **Expected behavior:** E-stop command reaches actuation within the latency budget regardless of AI/CPU load; unsafe proposals from any upstream module are rejected with a logged reason.
- **Safety constraints:** zero LLM→actuation direct path; safety container keeps elevated CPU/OOM priority under load.
- **Dashboard expectations:** `/field-learning/failure-cases` records any blocked-unsafe-proposal event; safety pass rate visible.
- **Pass criteria:** `SafetyAssertions.command_was_blocked()` / `estop_latency <= budget_ms`.
- **Fail criteria:** an unsafe command executes, or E-stop latency exceeds budget under full load.
- **Recovery behavior:** SAFE_STOP state, requires explicit operator/maintainer clear.
- **Logs required:** every supervisor decision (approve/block + reason), e-stop trigger timestamps.
- **Metrics required:** safety pass rate, emergency-stop reliability (latency p50/p99, miss rate).
- **CI-safe test strategy:** mocked command bus + supervisor decision table, asserted via `safety_assertions.py`.
- **Simulation strategy:** `bonbon_simulation` injects concurrent synthetic load while replaying stop triggers.
- **Hardware-gated strategy:** `pi_gated` + `safety` — physical GPIO e-stop button latency under real full AI load is BLOCKED off-robot.

## 4. Sensor Failure

- **Purpose:** prove the robot degrades safely (never unsafely) when any sensor drops out, alone or combined.
- **Risk:** CRITICAL.
- **Modules:** `bonbon_hal`, `bonbon_perception`, `bonbon_safety`, `bonbon_perception_efficiency`.
- **Environment variables:** single-sensor loss, multi-sensor loss, intermittent flapping sensor.
- **Human variables:** human present during the loss (must still be protected).
- **Robot state variables:** any.
- **Sensor variables:** camera lost, lidar lost, mic lost, IMU drift, depth sensor lost.
- **AI model variables:** n/a.
- **Expected behavior:** loss of a non-safety sensor degrades the dependent capability and is logged; loss of a safety-relevant sensor (lidar) forces SAFE_STOP, never "carry on blind."
- **Safety constraints:** `pi_efficiency_profile.never_disable` set is honored even with sensors down.
- **Dashboard expectations:** sensor health visible per-sensor, not aggregated away.
- **Pass criteria:** correct degraded-capability set per `PiEfficiencyProfile.modules_to_shed`; safety-critical sensors trigger SAFE_STOP.
- **Fail criteria:** robot continues an unsafe action (navigation/actuation) using stale/absent sensor data.
- **Recovery behavior:** auto-recover capability when the sensor returns; logged recovery event.
- **Logs required:** sensor-loss timestamp, capability shed, recovery timestamp.
- **Metrics required:** degraded-mode recovery rate, field failure rate by sensor.
- **CI-safe test strategy:** inject synthetic sensor-health dicts into `PiEfficiencyProfile`/safety gate.
- **Simulation strategy:** `bonbon_simulation` flips simulated sensor topics off mid-run.
- **Hardware-gated strategy:** `pi_gated` — physically unplugging a sensor on a live Pi.

## 5. Power and Thermal

- **Purpose:** prove compute/behavior scale down before thermal throttling or brownout, never after.
- **Risk:** HIGH.
- **Modules:** `bonbon_perception_efficiency` (load shedding, thermal), `bonbon_hal` (battery).
- **Environment variables:** ambient temp ramps, sustained high CPU.
- **Human variables:** none (background condition during any interaction).
- **Robot state variables:** any, plus explicit low-battery and docking-for-charge.
- **Sensor variables:** thermal sensor read, battery percentage.
- **AI model variables:** active model load (heavier models raise thermal pressure).
- **Expected behavior:** 75°C triggers caution-tier load shedding before 90°C SAFE_STOP threshold; low battery triggers a docking behavior, never a mid-task abrupt stop without warning.
- **Safety constraints:** safety pipeline itself is never shed (`never_disable`).
- **Dashboard expectations:** live CPU/mem/temp on `/pi/efficiency`.
- **Pass criteria:** shedding occurs at the configured thresholds, in `shed_order`.
- **Fail criteria:** thermal throttle or brownout reached without prior shedding.
- **Recovery behavior:** capabilities restored in reverse shed order once temp/battery recovers.
- **Logs required:** thermal/battery time series, shed/restore events.
- **Metrics required:** CPU/memory/temperature stability, degraded-mode recovery rate.
- **CI-safe test strategy:** existing 10 `test_pi_efficiency_scenarios.py` tests with synthetic temp/CPU readings.
- **Simulation strategy:** synthetic ramping-temperature generator feeding the same controller.
- **Hardware-gated strategy:** `pi_gated` — `vcgencmd get_throttled`/measured CPU% under real sustained load.

## 6. Navigation and Obstacle Avoidance

- **Purpose:** prove the robot reaches goals while never colliding, across crowding/lighting/passage-width variation.
- **Risk:** CRITICAL.
- **Modules:** `bonbon_navigation`, `bonbon_spatial`, `bonbon_safety`.
- **Environment variables:** corridor/lobby/reception/crowded-mall/narrow-passage, lighting variants.
- **Human variables:** static/moving people, wheelchair user, child nearby, unknown vs known person crossing path.
- **Robot state variables:** navigating, turning, docking.
- **Sensor variables:** lidar/camera nominal vs degraded.
- **AI model variables:** obstacle-classifier confidence variants.
- **Expected behavior:** path replanned around obstacles with a safety margin; robot yields to humans, especially wheelchair users and children.
- **Safety constraints:** hard stop before any predicted-collision state; never executes a path the safety gate didn't clear.
- **Dashboard expectations:** navigation success rate visible.
- **Pass criteria:** `NavigationAssertions.reached_goal_without_collision()` and margin maintained.
- **Fail criteria:** collision, near-miss below margin, or goal timeout without a logged safety reason.
- **Recovery behavior:** replan or yield-and-wait; SAFE_STOP only as a last resort.
- **Logs required:** planned vs executed path, obstacle events, margin violations.
- **Metrics required:** navigation success rate, average response latency.
- **CI-safe test strategy:** synthetic costmaps + obstacle tracks through the planner's pure-Python core.
- **Simulation strategy:** `bonbon_simulation` full scenario playback (primary validation surface for this family).
- **Hardware-gated strategy:** `pi_gated` — real corridor run with a safety spotter.

## 7. Object Recognition

- **Purpose:** prove detection precision/recall and graceful behavior under occlusion/lighting/novel-object conditions.
- **Risk:** MEDIUM.
- **Modules:** `bonbon_object_intelligence`, `bonbon_vision`, `bonbon_ai_runtime`.
- **Environment variables:** all 9 `Environment` values, all 5 `Lighting` values.
- **Human variables:** n/a (objects, not people).
- **Robot state variables:** idle, navigating (motion blur).
- **Sensor variables:** camera nominal/lost, AI HAT unavailable (CPU fallback).
- **AI model variables:** confidence thresholds, runtime kind (hailo/cpu/mock).
- **Expected behavior:** known classes detected above threshold; low-confidence detections are reported as uncertain, not asserted as fact.
- **Safety constraints:** a misdetected object must never become an actuation trigger without the safety gate's own corroboration.
- **Dashboard expectations:** object-detection precision/recall on `/validation/test-results`.
- **Pass criteria:** `PerceptionAssertions.detection_within_iou_and_class()`; low-confidence path correctly suppressed.
- **Fail criteria:** false positive used as a behavior trigger, or a target-class miss above the required recall floor.
- **Recovery behavior:** re-query next frame; never act on a single-frame detection alone for anything consequential.
- **Logs required:** per-frame detections + confidence, ground-truth comparison where available.
- **Metrics required:** object detection precision/recall.
- **CI-safe test strategy:** fixture frames with known ground truth, `MockRuntime` detector.
- **Simulation strategy:** simulated camera feed with synthetic labeled objects.
- **Hardware-gated strategy:** `ai_hat_gated` — Hailo-accelerated detection accuracy/latency on real hardware.

## 8. Multi-Person Tracking

- **Purpose:** prove stable identity across frames/occlusion, no ID switches, no cross-person mix-up.
- **Risk:** HIGH.
- **Modules:** `bonbon_multi_person_tracker`, `bonbon_speaker_intelligence`.
- **Environment variables:** all crowd-density `People` values (one/two/five/crowd).
- **Human variables:** known vs unknown person, off-camera speaker, person re-entering frame.
- **Robot state variables:** idle, navigating.
- **Sensor variables:** camera nominal/intermittent.
- **AI model variables:** re-identification embedding confidence.
- **Expected behavior:** consistent track ID per person through brief occlusion; the active-speaker/addressee assignment matches the actual speaking person.
- **Safety constraints:** identity confusion must never authorize an action meant for a different person (e.g., access/handoff).
- **Dashboard expectations:** person-ID switch rate on `/validation/production-score`.
- **Pass criteria:** `PerceptionAssertions.no_identity_mixup()`, ID-switch count below threshold for the scenario's occlusion profile.
- **Fail criteria:** an ID switch attributed to the wrong person, or two simultaneous tracks merged.
- **Recovery behavior:** re-acquire and re-identify; if confidence is too low, ask for clarification rather than guess.
- **Logs required:** track lifecycle (spawn/merge/split/lost), confidence at each transition.
- **Metrics required:** person ID switch rate.
- **CI-safe test strategy:** synthetic multi-track sequences with known occlusion ground truth (existing `test_multi_person_perception_scenarios.py` pattern).
- **Simulation strategy:** simulated crowd walk-throughs with scripted occlusion.
- **Hardware-gated strategy:** `pi_gated` — real multi-person room test.

## 9. Gesture Understanding

- **Purpose:** prove gestures (including conflicting/ambiguous ones) map to correct, safe behavior.
- **Risk:** HIGH.
- **Modules:** `bonbon_gesture`, `bonbon_behavior_engine`, `bonbon_safety`.
- **Environment variables:** lighting variants (gesture recognition is light-sensitive).
- **Human variables:** all `Gestures` values including `conflicting gestures` and `none`.
- **Robot state variables:** idle, speaking, navigating (must interrupt correctly on stop-palm).
- **Sensor variables:** camera nominal/degraded.
- **AI model variables:** gesture-classifier confidence.
- **Expected behavior:** `stop palm` always maps to an immediate safety-relevant halt regardless of context; ambiguous/conflicting gestures trigger clarification, not a guess.
- **Safety constraints:** gesture false triggers must never command actuation directly — gesture intent goes through the behavior engine and safety gate.
- **Dashboard expectations:** gesture false-trigger rate on `/validation/production-score`.
- **Pass criteria:** correct mapped behavior for unambiguous gestures; clarification path taken for `conflicting gestures`/low confidence.
- **Fail criteria:** wrong action taken, or `stop palm` not honored within the response-latency budget.
- **Recovery behavior:** re-prompt ("did you mean...?") or no-op on persistent ambiguity.
- **Logs required:** gesture classification + confidence, resulting behavior decision.
- **Metrics required:** gesture false trigger rate, behavior correctness rate.
- **CI-safe test strategy:** synthetic gesture-confidence vectors through `bonbon_gesture`'s pure-Python classifier.
- **Simulation strategy:** scripted gesture sequences against the simulated camera feed.
- **Hardware-gated strategy:** `pi_gated` — live camera gesture recognition accuracy.

## 10. Speech and Speaker Diarization

- **Purpose:** prove correct transcription, speaker attribution, and language/accent robustness, with safety-phrase priority.
- **Risk:** HIGH.
- **Modules:** `bonbon_speech`, `bonbon_speaker_intelligence`, `bonbon_tts`.
- **Environment variables:** noisy area, quiet area.
- **Human variables:** all `Speech` values (silent/clear/noisy/overlapping/accent/language/emergency phrase/angry/confused) × off-camera speaker.
- **Robot state variables:** idle, speaking (must support barge-in on emergency phrase).
- **Sensor variables:** mic nominal/lost.
- **AI model variables:** ASR confidence, diarization confidence, language-ID confidence.
- **Expected behavior:** an emergency phrase ("stop", "help", "emergency") is recognized and escalated even mid-utterance and mid-TTS; diarization correctly attributes overlapping speech to the louder/nearer speaker or flags ambiguity.
- **Safety constraints:** emergency-phrase detection routes through the safety path, not just the conversational LLM path.
- **Dashboard expectations:** speaker diarization error rate, active-speaker assignment accuracy.
- **Pass criteria:** `SpeechAssertions.transcript_matches()` within WER budget; emergency phrase always escalated.
- **Fail criteria:** missed emergency phrase, or wrong-speaker attribution causing a response to the wrong person.
- **Recovery behavior:** "I didn't catch that, could you repeat?" on low-confidence ASR rather than acting on a guess.
- **Logs required:** transcript + confidence, diarization assignment, escalation events.
- **Metrics required:** speaker diarization error rate, active speaker assignment accuracy.
- **CI-safe test strategy:** synthetic transcript/confidence fixtures through `bonbon_speaker_intelligence`'s pure-Python core.
- **Simulation strategy:** pre-recorded/public-dataset audio clips replayed through the pipeline (see `ONLINE_DATASET_STRATEGY.md`).
- **Hardware-gated strategy:** `pi_gated` — real mic array diarization in a live room.

## 11. Human-State Fusion

- **Purpose:** prove the fused human-state estimate (attention, emotion, engagement) is treated as an *uncertain signal*, not ground truth.
- **Risk:** MEDIUM.
- **Modules:** `bonbon_human_state_fusion`, `bonbon_affective_ai`.
- **Environment variables:** all.
- **Human variables:** elderly user, child nearby, conflicting affect cues (calm voice + distressed face).
- **Robot state variables:** any.
- **Sensor variables:** any combination of vision/speech available.
- **AI model variables:** per-modality confidence, fusion weight.
- **Expected behavior:** fused state confidence gates how strongly it influences behavior; low-confidence or conflicting-modality states never trigger a strong behavior change alone.
- **Safety constraints:** emotion/engagement estimates never gate the safety path (only speech/gesture/sensor safety signals do).
- **Dashboard expectations:** fusion confidence visible alongside behavior decisions in `/validation/test-results`.
- **Pass criteria:** behavior engine input shows the fused confidence and the correct downstream damping at low confidence.
- **Fail criteria:** a low-confidence/conflicting fused state drives a strong behavior change as if certain.
- **Recovery behavior:** fall back to neutral/no-adaptation behavior on low fusion confidence.
- **Logs required:** per-modality + fused confidence, behavior-engine input snapshot.
- **Metrics required:** behavior correctness rate (fused-state subset).
- **CI-safe test strategy:** synthetic per-modality confidence vectors, including deliberately conflicting ones.
- **Simulation strategy:** scripted conflicting-cue scenarios.
- **Hardware-gated strategy:** `pi_gated` — real-room cross-modal estimate, compared to human-reviewer label.

## 12. Behavior Engine Decisions

- **Purpose:** prove the behavior engine picks the correct, safe action given fused state + context, and never lets the LLM author actuation/navigation directly.
- **Risk:** CRITICAL.
- **Modules:** `bonbon_behavior_engine`, `bonbon_llm`, `bonbon_safety`.
- **Environment variables:** all.
- **Human variables:** all.
- **Robot state variables:** all.
- **Sensor variables:** nominal and degraded combinations.
- **AI model variables:** LLM response variants (including adversarial "ignore your safety rules" prompts).
- **Expected behavior:** behavior engine selects from its own constrained action set; an LLM suggestion is advisory text/dialogue only and is checked through `CommandAuthorizer`/safety gate before anything physical happens.
- **Safety constraints:** zero LLM→actuation/navigation topic coupling (this is independently re-verified every run, not assumed).
- **Dashboard expectations:** behavior correctness rate; any blocked LLM-attempted action surfaces on `/field-learning/failure-cases`.
- **Pass criteria:** `behavior_oracle.llm_did_not_act_directly()` true for every scenario; chosen action matches the expected-outcome table.
- **Fail criteria:** LLM output reaches `bonbon_actuation`/`bonbon_navigation` without passing through the authorizer + safety gate, or wrong action selected for unambiguous input.
- **Recovery behavior:** unrecognized/ambiguous context → safe default (no-op / ask clarification), never an improvised physical action.
- **Logs required:** behavior decision + inputs, LLM raw suggestion vs. authorized action (must differ in audit when LLM suggested something physical).
- **Metrics required:** behavior correctness rate.
- **CI-safe test strategy:** static topic-graph check (no LLM node subscribed by actuation/navigation) + decision-table tests with adversarial LLM stub outputs.
- **Simulation strategy:** full scripted dialogue + context scenarios through the real behavior engine with a stubbed LLM.
- **Hardware-gated strategy:** `pi_gated` — end-to-end live interaction confirming the same topic-graph isolation on the running robot.

## 13. Dashboard and Operator Control

- **Purpose:** prove the dashboard always reflects real backend state and operator actions are authorized + audited.
- **Risk:** MEDIUM.
- **Modules:** `bonbon_operator_api`, frontend.
- **Environment variables:** dashboard connected/disconnected, slow network.
- **Human variables:** operator with/without required permission.
- **Robot state variables:** any.
- **Sensor variables:** n/a.
- **AI model variables:** n/a.
- **Expected behavior:** every card reads live backend data (never a hardcoded PASS); privileged actions (mode select, e-stop clear) require `require_permission`.
- **Safety constraints:** a disconnected dashboard never blocks the robot's own safety path (dashboard is observability/control-plane, not safety-plane).
- **Dashboard expectations:** is itself the subject under test here.
- **Pass criteria:** `DashboardAssertions.endpoint_reflects_backend_state()`; unauthorized action correctly rejected (403).
- **Fail criteria:** stale/fake data shown, or an unauthorized action succeeds.
- **Recovery behavior:** dashboard reconnect resyncs state; robot continues operating autonomously while disconnected.
- **Logs required:** API access log, permission-check outcomes.
- **Metrics required:** dashboard accuracy rate.
- **CI-safe test strategy:** FastAPI `TestClient` against real (file/in-memory) backends, exactly as `test_deployment_api.py` already does.
- **Simulation strategy:** n/a — dashboard is tested directly, not simulated.
- **Hardware-gated strategy:** `pi_gated` — dashboard against a live robot, including disconnect/reconnect.

## 14. Degraded Mode

- **Purpose:** prove the robot keeps operating safely with reduced capability instead of failing hard, across every trigger.
- **Risk:** CRITICAL.
- **Modules:** `bonbon_perception_efficiency`, `bonbon_ai_runtime`, `bonbon_safety`.
- **Environment variables:** any.
- **Human variables:** human present during degradation (must remain protected).
- **Robot state variables:** `degraded mode`, `dashboard disconnected`, `low battery`.
- **Sensor variables:** any single/multi failure from family 4.
- **AI model variables:** Hailo unavailable, model load failure.
- **Expected behavior:** matches `config/runtime/degraded_mode.yaml` shed order; safety-critical modules in `never_disable` stay up under every trigger combination.
- **Safety constraints:** the one constraint this whole family exists to prove.
- **Dashboard expectations:** `/pi/degraded-mode` shows live shed state + reason.
- **Pass criteria:** correct shed set for the trigger combination; `never_disable` modules always present; recovery restores in reverse order.
- **Fail criteria:** a `never_disable` module shed, or no degraded-mode entry when a trigger condition was met.
- **Recovery behavior:** auto-restore on trigger clearing, logged.
- **Logs required:** trigger condition, shed set, recovery set, durations.
- **Metrics required:** degraded mode recovery rate.
- **CI-safe test strategy:** existing 11 `test_pi_efficiency_scenarios.py` + combinatorial trigger-stacking tests.
- **Simulation strategy:** simulated multi-trigger stacking (e.g., thermal + Hailo-loss simultaneously).
- **Hardware-gated strategy:** `pi_gated` — real degraded-mode trigger and recovery on a Pi.

## 15. Field Pilot Learning

- **Purpose:** prove the field-learning loop itself: failures get captured, anonymized, reviewed, and turned into regression tests without leaking raw biometric data.
- **Risk:** HIGH (privacy) / MEDIUM (functional).
- **Modules:** `bonbon_field_learning` (Phase 6), `bonbon_behavior_validation`.
- **Environment variables:** pilot deployment site (real-world, out of the lab).
- **Human variables:** real users, real consent state (debug mode on/off).
- **Robot state variables:** any.
- **Sensor variables:** any.
- **AI model variables:** any.
- **Expected behavior:** any oracle-flagged failure is logged as anonymized metadata by default; raw snapshots are stored only when debug mode was explicitly enabled for that session; every captured failure can be exported to a human review queue and, once labeled, becomes a new regression scenario.
- **Safety constraints:** no raw face/audio storage without explicit consent/debug mode; PII-bearing fields are never written to the default event store.
- **Dashboard expectations:** `/field-learning/failure-cases`, `/field-learning/regression-tests`, `/privacy/data-collection-status`.
- **Pass criteria:** `FailureCaseLogger` output contains zero raw biometric fields outside debug mode; every reviewed+labeled case produces exactly one new regression scenario file.
- **Fail criteria:** raw audio/face bytes present in the default (non-debug) event store, or a labeled failure that never produces a regression test.
- **Recovery behavior:** n/a (this family observes recovery elsewhere; its own "recovery" is the regression test closing the gap).
- **Logs required:** anonymized event records, review-queue state, dataset version bumps, model evaluation deltas.
- **Metrics required:** field failure rate, regression pass rate.
- **CI-safe test strategy:** unit tests on the logger/store/queue/exporter/generator using synthetic events, asserting the privacy contract.
- **Simulation strategy:** synthetic failure-event stream replayed through the whole loop.
- **Hardware-gated strategy:** `field_pilot` — real pilot-site data is opt-in and never required for CI; ingestion format is validated, not the live pilot itself.
