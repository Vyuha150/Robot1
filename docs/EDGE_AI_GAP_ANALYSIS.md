# Edge AI Gap Analysis

Edge AI Runtime brief, Phase 1. Numbered `GAP-E1..E12` to avoid colliding
with the pre-existing `GAP-1..11` numbering in
`docs/AI_MODEL_GAP_ANALYSIS.md` (still valid, not superseded). Ordered by
severity: safety-critical first, then duplication/efficiency, then
missing-but-not-dangerous.

## Safety-critical (fix before anything else in this brief)

**GAP-E1 — FIXED.** LLM could trigger a real Nav2 goal through a
fail-open authorizer. `bonbon_llm/safety/authorization.py::CommandAuthorizer`'s
default-before-first-heartbeat state permitted navigation; this was the
live path `llm_orchestrator_node` actually uses, not
`bonbon_motion_approval_gateway`. Direct violation of this brief's rule
2. Full trace: `SAFETY_SEPARATION_AUDIT.md` Finding 1.

Fixed ahead of Phase 7, at the user's explicit request, by:
1. `SafetySnapshot.safe_default()` now fails closed (`navigation_permitted=False`,
   `actuation_permitted=False`, `state_id=SAFETY_INITIALIZING`) instead
   of permissive.
2. `llm_orchestrator_node._get_safety_snapshot()` now also tracks
   *staleness*, not just absence -- a `_last_safety_at` timestamp is set
   whenever `/bonbon/safety/state` is received, and any snapshot older
   than 2.0s (matching `SafetyStopBridge.watchdog_timeout_sec`) falls
   back to the fail-closed default. This closes a second, arguably more
   dangerous window the original audit hadn't separately named: the
   Safety Supervisor going silent *mid-operation* (crash, network
   partition), not just the first-boot race.
3. Regression tests added: `test_authorization.py::test_safe_default`
   (updated to assert fail-closed) +
   `test_safe_default_denies_navigation_and_actuation_via_authorizer`
   (new); `test_llm_orchestrator.py::TestGetSafetySnapshotFailsClosed`
   (3 new tests: no message yet, fresh message passes through, stale
   message falls back). 108/108 targeted tests pass; 666/666 broader
   `tests/llm_local/` + `tests/production/` regression pass, no
   collateral breakage.

**Note**: this fix closes the fail-open authorization gap itself.
Finding 2 (the propose/approve gateway still has no subscriber on its
decision topic) and Finding 5 (the Nav2→wheel velocity path is dead
code) remain open, tracked for full Phase 7.

**GAP-E2 — FIXED.** The propose/approve safety gateway was disconnected
from execution: `bonbon_motion_approval_gateway` published
`BehaviorDecision` to `/bonbon/motion/approved_command`, which had zero
subscribers repo-wide -- it only fed the dashboard's audit/observability
view. Root cause traced further than the original audit knew: neither
`BehaviorProposal`/`BehaviorDecision`'s pose fields survived the
gateway's own `ProposalInput`/`DecisionResult` dataclasses, and
`bonbon_behavior_engine` already had a `BehaviorProposal` publisher
wired up but never once called.

Fixed by:
1. Adding `nav_goal_pose`/`nav_goal_label` to `BehaviorDecision.msg`, and
   `nav_goal_x/y/yaw/label` to `ProposalInput`/`DecisionResult` in
   `bonbon_motion_approval_gateway/core/approval_gateway.py`, threaded
   through `_approve()` and the node's `_cb_proposal()`.
2. New `bonbon_behavior_engine/core/behavior_recommendation_bridge.py`
   (pure, tested) + a new `_on_behavior_recommendation` handler in
   `behavior_engine_node.py` that finally uses the existing-but-dead
   `BehaviorProposal` publisher to forward `navigate_to_goal`/
   `approach_person` recommendations to the gateway.
3. `bonbon_navigation/nodes/navigation_node.py`'s `_on_behavior_recommendation`
   now handles ONLY `stop_navigation` (cancellation); a new
   `_on_approved_command` handler, gated by the new pure
   `bonbon_navigation/safety/approved_command_gate.should_dispatch_navigation()`,
   is the ONLY path that enqueues a Nav2 goal -- fed exclusively by the
   gateway's real approval.

Regression-tested: 3 new pose-passthrough tests
(`bonbon_motion_approval_gateway/tests/test_approval_gateway.py`), 6 new
bridge-conversion tests (`bonbon_behavior_engine/tests/test_behavior_recommendation_bridge.py`),
7 new dispatch-gating tests (`bonbon_navigation/tests/test_approved_command_gate.py`).
`SAFETY_SEPARATION_AUDIT.md` Finding 2.

**GAP-E3/E5 — FIXED.** Nav2→wheel-motor velocity path was dead code:
topic-name mismatch (`cmd_vel_raw` vs the docstring's aspirational
`safety_gate/cmd_vel`) plus a `_publish_gated_vel` that built a `Twist`
and never called `.publish()` -- no publisher for the topic even
existed. Fixed: added the real `/bonbon/cmd_vel_raw` publisher (matching
`safety_gate_node`'s actual subscription exactly, same QoS), wired
`_publish_gated_vel` to actually publish, and corrected the stale
topic-name references in both `navigation_node.py`'s and
`safety_stop_bridge.py`'s docstrings. `SAFETY_SEPARATION_AUDIT.md`
Finding 5.

**GAP-E4 — FIXED. Pi-3's cross-Pi heartbeat doesn't reflect real
component health.** `distributed_safety_node` hardcoded `status = 0 # OK`
regardless of whether `safety_gate_node`/`navigation_node` were actually
alive. Fixed: the node now subscribes to `watchdog_node`'s real
`/bonbon/safety/{critical,important}_node_crashed` flags and derives its
heartbeat status honestly via a new pure `local_health_status()` function
in `core/heartbeat_monitor.py` (ERROR on critical crash, WARN on
important crash or no signal received yet past a startup grace period,
OK otherwise — never fabricated). 6 new tests in
`tests/test_heartbeat_monitor.py::TestLocalHealthStatus` (18/18 passing
in the package). See `EDGE_AI_RUNTIME_FINAL_REPORT.md`.

**GAP-E5 — Safety enforcement is scattered across 5-6 independently
coded mechanisms with inconsistent fail-open/fail-closed defaults.**
Fully audited this pass — see
[`EDGE_AI_SAFETY_MECHANISM_AUDIT.md`](EDGE_AI_SAFETY_MECHANISM_AUDIT.md)
for the complete evidence table. Confirmed: 4 of 6 mechanisms were
already fail-closed; 2 were fail-open (`SafetyCommandFilter` on internal
error, `CommandRiskClassifier`/`ProposalEvaluator` on
unrecognized/gesture-sourced commands). `SafetyCommandFilter`'s error
handling is now fixed to fail-closed (regression test:
`TestInternalErrorFailsClosed`). `CommandRiskClassifier`/`ProposalEvaluator`'s
fail-open default is a considered, heavily-tested design choice, not
changed directly — instead mitigated via Finding 8's fix (below), which
adds an independent `SafetySeparationGuard` check covering exactly the
gap that default leaves open. Full unification of all 6 mechanisms
behind one shared authority remains a deliberate, tracked follow-up, not
attempted in one pass against 5 already-safety-critical modules.

**GAP-E6 — FIXED. No test exercised the real topic-graph chain for
safety separation.** `tests/safety/` was empty. Added
`tests/safety/test_end_to_end_navigation_safety_chain.py` — 9 tests
chaining the REAL pure decision functions each node in the GAP-E1/E2/E3
chain actually calls
(`behavior_recommendation_bridge.recommendation_to_proposal()` →
`MotionApprovalGateway.evaluate()` → `should_dispatch_navigation()`), in
the real order the real topic graph invokes them, with no mocks of the
safety-decision logic itself — including the exact GAP-E1 scenario
(navigation blocked when `navigation_permitted=False`). A full
ROS2-topic-wiring test (real pub/sub) remains out of reach in this dev
sandbox (no rclpy) — documented as the residual piece of this gap.

## Duplication / architecture (fix by consolidating, not adding)

**GAP-E7 — `bonbon_edge_ai_runtime`'s literal 12-module spec would
duplicate 5 already-working modules** if built from scratch:
`cache_manager` (duplicates `response_cache.py` + TTS phrase cache),
`resource_guard` (duplicates `resource_monitor.py` +
`load_shedding_controller.py` + `pi2_llm_guard.py`),
`degraded_mode_manager` (duplicates the existing one under the identical
name in `bonbon_perception_efficiency`), and the implied three-Pi
heartbeat/monitor work (duplicates `bonbon_distributed_safety` +
`bonbon_authority_manager`). See `DUPLICATE_PIPELINE_AUDIT.md` for the
full table and the consolidation plan.

**GAP-E8 — No cross-capability task router exists.** Confirmed by direct
search — zero hits for `TaskRouter`/`RequestDispatcher`. Per-modality
routers exist (ASR, TTS, `ModelRuntimeSelector`) but nothing routes
across rule/cache/RAG/LLM/vision/escalation. `pi_human_ai.yaml`'s
`resolution_order` config key is read by zero code. This is genuinely
new, needed work (Phase 4).

**GAP-E9 — FIXED (deprecated, not deleted). Two independent RAG
implementations, one dead.** `bonbon_data_stores/rag/{chroma_store.py,rag_query_engine.py}`
is constructed by `SQLiteMemoryStore` but never wired to any live ROS2
topic/service (corrected finding: not literally unimported — `store.py`
does construct it — but functionally dead, confirmed via repo-wide grep
for real callers). Fixed: both files' module docstrings, plus
`store.py`'s construction site, now carry an explicit, unmissable
deprecation notice (with a runtime `logger.warning()` on construction)
pointing to the real, live implementation
(`bonbon_llm.core.rag_retriever.RAGRetriever`). Not deleted — doing so
would require an unrelated refactor of `SQLiteMemoryStore`'s facade
contract and would break `tests/test_backup.py`/`tests/test_rag_store.py`,
which still exercise it directly.

**GAP-E10 — FIXED (deprecated, not deleted). Two independent
object-detection stacks** (`bonbon_vision` vs `bonbon_perception`,
pre-existing GAP-2). Research confirmed `bonbon_perception`'s
`YoloPersonDetector`/`detection_node.py` is the weaker duplicate: no
launch file anywhere in the repo (unwired), less test coverage, and the
whole package was already independently quarantined by a 2026-06-30
efficiency audit (`bonbon_perception/README.md`). `bonbon_vision`'s
`YoloDetector`/`ObjectDetectorRuntimeAdapter` is canonical: actually
launched, registry-endorsed, routed through `bonbon_ai_runtime.RuntimeSelector`.
Fixed: added an explicit per-class deprecation docstring to
`yolo_person_detector.py` (the package README's quarantine notice didn't
cover the individual detector class) pointing to the canonical stack.

## Found during Phase 9 (event-driven processing verification)

**GAP-E13 — FIXED. TTS never actually checked the phrase cache first.**
`TTSRouter.speak()` always consulted the runtime-availability chain
(Sarvam→Piper→sherpa-onnx→cached-phrase→text-only) regardless of
whether the requested text was one of the 6 known cached hospital
phrases — meaning a known phrase was re-synthesized via Piper every
single call (measured 2.5–5.8s of real, avoidable latency in this
repo's own benchmark runs) instead of served instantly. Directly
violated this brief's Phase 9 rule ("use cached phrase first, synthesize
only if cache miss"). Fixed: `speak()` now checks a real file-existence
cache lookup first when a valid `phrase_key` is given, only falling
through to the engine chain on a genuine miss. Also fixed a related
honesty gap: the cached-phrase invoker used to return a path string
without checking the file actually existed. 8 tests (2 new files' worth)
verify both the fast path and the honest-miss path.

**GAP-E14 — FIXED. RAG retrieval has no exact-match-first step.**
`bonbon_llm/core/rag_retriever.py::retrieve_with_scores()` went straight
to embedding-based cosine similarity for every query. Fixed: a new
`add_faq_document(question, answer)` method registers a document with a
canonical question in `metadata["question"]`; `retrieve_with_scores()`
now checks for a case/whitespace-normalized exact match against any such
document BEFORE computing an embedding at all, returning it immediately
with `score=1.0`. Documents added via the existing `add_document()` (the
entire default knowledge base, and every pre-existing caller) never set
`metadata["question"]` and are completely unaffected — verified via 6
new tests in `tests/test_rag_retriever.py::TestExactMatchFirst`,
including a `monkeypatch` proof that `_embed()` is never called on the
exact-match path. `bonbon_edge_ai_runtime`'s `RagResultCache` (Phase 6)
remains a separate, complementary cache (identical prior query+context,
not exact-match-on-content) — this is the piece that was missing
alongside it, not a duplicate of it.

**GAP-E8 — FIXED. LLM resolution_order not enforced.**
`pi_human_ai.yaml`'s `resolution_order: [rule_engine, rag, llm]` was
declared but read by zero live code. Fixed: `llm_orchestrator_node.py`
now lazily constructs a real `TaskRouter` (degrades to `None`, zero
behavior change, if `bonbon_edge_ai_runtime` isn't installed) and
consults it at the top of `_process_intent`, BEFORE the cache/RAG/LLM
pipeline. Scoped deliberately narrow: only the `task_type == "emergency"`
route is currently short-circuited (skips RAG/LLM entirely, dispatches
the existing-but-previously-never-triggered `"emergency"` fallback
template at `TTSRequest.PRIORITY_HIGH`, and authorizes an `alert_safety`
behavior through the existing, unmodified `CommandAuthorizer`) — every
other routing outcome (navigation/appointment/FAQ/small-talk) falls
through to the exact same pipeline as before this fix, unchanged. 5 new
tests in `tests/test_llm_orchestrator.py::TestEmergencyRuleEngineShortCircuit`,
including an explicit degradation-guard test proving the pipeline
behaves identically when `bonbon_edge_ai_runtime` is absent.

**ASR/vision event-gating — confirmed correct, no fix needed.**
Re-verified `bonbon_speech_ai/speech_pipeline.py`'s `vad_confirmed` gate
and `bonbon_vision/preprocessing/frame_throttler.py::FrameThrottler` are
both genuinely wired and enforced exactly as the brief's Phase 9 rules
require.

## Missing but not dangerous

**GAP-E11 — No RAG result cache.** The LLM response cache indirectly
skips RAG on a hit, but there's no cache internal to the retriever
itself for cases where the LLM answer differs but the retrieved context
would be identical. New work for Phase 6, additive not duplicative.

**GAP-E12 — FIXED. Gesture recognition had no VAD-equivalent event
gate.** `bonbon_gesture/nodes/gesture_node.py` processed every incoming
frame that passed its modulo-N throttle regardless of whether anyone was
in view. Fixed: new pure `logic/frame_gate.py::should_process_frame()`
adds a presence gate — frames are skipped once `/bonbon/vision/persons`
has reported (at least once) that nobody is currently tracked, honestly
distinguishing "never received a persons message yet" (must not gate,
startup race) from "received one and it was empty" (safe to gate). New
`gate_on_person_presence` config/ROS2 parameter (default `True`). 7 new
tests in `tests/test_frame_gate.py` (101/101 passing in the package).

## Finding 8 (docs/SAFETY_SEPARATION_AUDIT.md) — FIXED

`bonbon_behavior_engine`'s own `_dispatch_proposal()` used only
`ProposalEvaluator`/`CommandRiskClassifier` for gesture/speech-sourced
proposals, bypassing `bonbon_motion_approval_gateway`/`SafetySeparationGuard`
entirely, and `CommandRiskClassifier` is only actually invoked when
`source == "llm"` — meaning gesture- and speech-intent-sourced proposals
(the majority of calls into this method) never got real content-risk
screening at all. Fixed: `SafetySeparationGuard` is now consulted as an
independent, additional check in `_dispatch_proposal()` before
`speak`/`gesture` dispatch — defense-in-depth, not a replacement for
`ProposalEvaluator` or the real, tested, fail-closed `ActuationSafetyGate`
already downstream of `/bonbon/behavior/actuation`. Degrades to a no-op
if `bonbon_edge_ai_runtime` isn't installed. See
`EDGE_AI_SAFETY_MECHANISM_AUDIT.md` for the full picture across all 6
pre-existing mechanisms.

## Closing status (all 9 previously-open gaps + Finding 8)

GAP-E4, E5, E6, E8, E9, E10, E12, E14, and Finding 8 were all
open/tracked as of `EDGE_AI_RUNTIME_FINAL_REPORT.md`'s original PARTIAL
verdict. All 9 are now fixed or (for E5/E9/E10, where full deletion or
full unification would be a disproportionate, high-risk change against
already-critical or already-tested code) mitigated with a real,
targeted, regression-tested fix plus honest documentation of what
remains a deliberate, tracked follow-up rather than silently dropped.
Zero regressions across the ~955-test repo-root suite — see
`EDGE_AI_RUNTIME_FINAL_REPORT.md`'s update for the full verification.
