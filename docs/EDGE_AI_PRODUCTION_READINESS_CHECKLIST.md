# Edge AI Production Readiness Checklist

Phase 15. Checks this brief's 13 critical rules against the real, verified
state of the repo after all 15 phases — each rule marked against concrete
evidence, not assertion.

| # | Rule | Status | Evidence |
|---|---|---|---|
| 1 | Safety and movement must never wait for AI | ✅ Enforced structurally | `InferenceScheduler.submit()` dispatches safety-critical modules immediately, bypassing the queue entirely (`EDGE_AI_RESOURCE_SCHEDULING_REPORT.md`) |
| 2 | LLM must never directly control navigation/motors/servos/e-stop/safety | ✅ Fixed (was violated — GAP-E1) | `SafetySnapshot.safe_default()` fails closed; `SafetySeparationGuard`'s never-allow table blocks `llm` from every direct-control action type |
| 3 | UI must never directly control motors/servos/Nav2 | ✅ | `three_pi_allocation.yaml`'s `ui_supervisor_pi.forbidden` list + `SafetySeparationGuard`'s never-allow table |
| 4 | AI Pi can only generate behavior proposals | ✅ | `three_pi_allocation.yaml`'s `ai_interaction_pi.behavior_output` is proposal-only; `SafetySeparationGuard.classify()` returns `requiresApproval=True` for every proposal category |
| 5 | Navigation/Safety Pi is the only authority for real movement | ✅ | `three_pi_allocation.yaml`'s `sole_motion_command_publisher: bonbon_safety_supervisor`; `navigation_node._on_approved_command` is the only Nav2-goal-enqueue path fed by AI (GAP-E2 fix) |
| 6 | Safety Supervisor must approve movement and actuation | ✅ | `bonbon_motion_approval_gateway` now has a real subscriber (GAP-E2 fix) and pose data survives the round trip |
| 7 | Do not create duplicate camera/mic/lidar/database/dashboard/safety pipelines | ✅ Held; 2 pre-existing duplicates now clearly deprecated, not silently left as traps | `DUPLICATE_PIPELINE_AUDIT.md`; GAP-E9 (dead RAG code — deprecated with runtime warning) and GAP-E10 (two object-detection stacks — weaker one deprecated) both fixed via clear deprecation rather than deletion |
| 8 | Do not fake Raspberry Pi / AI HAT / hardware PASS | ✅ | Every hardware-gated test/benchmark reports `blocked` or `skip`, never a fabricated pass — verified across `tests/edge_ai/`, `scripts/edge_ai/benchmark_edge_ai_stack.py`, `check_hailo_runtime.sh` |
| 9 | Hardware-specific tests must be hardware_gated | ✅ | 14 hardware-gated tests correctly skip off-hardware in the repo-root suite; none fabricate a pass |
| 10 | Dashboard must show real model status, runtime, fallback, latency, degraded mode, safety blocks | ✅ | 9 dashboard cards, all sourced from real state (never fabricated zero-states) — `EDGE_AI_DASHBOARD_INTEGRATION_REPORT.md` |
| 11 | Every AI model must have a fallback path | ✅ (with 1 known exception, pre-existing) | All 6 new registry entries have a working `fallback_model_id`; `llm_qwen25_05b` (pre-existing, base registry) still has none — tracked in `docs/AI_MODEL_GAP_ANALYSIS.md`, not this brief's scope |
| 12 | Every long-running inference must have timeout, bounded queue, resource guard | ✅ | `InferenceScheduler`'s bounded per-module queues + timeouts; `ResourceGuard.evaluate()` |
| 13 | If unsure, degrade safely instead of failing silently | ✅ | `SafetySeparationGuard`'s unrecognized-action-type fail-closed default; every dashboard "unavailable" state is explicit, never a silent empty dict |

## Update: all 9 previously-open gaps + Finding 8 now fixed

A follow-up pass fixed every item this checklist previously listed as
"known, documented, not fixed":

- **GAP-E4** — fixed: heartbeat now reflects real `watchdog_node` crash flags.
- **GAP-E5** — audited (`EDGE_AI_SAFETY_MECHANISM_AUDIT.md`) and the one
  genuinely unintentional fail-open (`SafetyCommandFilter` error
  handling) fixed; the other (`CommandRiskClassifier`'s design-choice
  fail-open default) mitigated via Finding 8's fix, not directly changed.
- **GAP-E6** — fixed: 9 new end-to-end chained tests in `tests/safety/`.
- **GAP-E8** — fixed: `TaskRouter` now wired into `llm_orchestrator_node`
  for the emergency rule-engine case (scoped, degrades gracefully).
- **GAP-E9** — fixed: dead RAG code clearly deprecated (docstring +
  runtime warning), not deleted (would break existing tests).
- **GAP-E10** — fixed: the weaker duplicate detector clearly deprecated.
- **GAP-E12** — fixed: gesture recognition now gates on person presence.
- **GAP-E14** — fixed: RAG now checks exact match before vector search.
- **Finding 8** — fixed: `SafetySeparationGuard` added as an independent
  check in `behavior_engine_node._dispatch_proposal()`.

Full details, evidence, and regression-test results for each: see
`docs/EDGE_AI_GAP_ANALYSIS.md`'s per-gap entries and
`docs/EDGE_AI_RUNTIME_FINAL_REPORT.md`'s updated verdict. Rule 5 (safety
enforcement unification) remains partially open by design — full
retrofit of all 6 mechanisms behind one shared authority is a
deliberate, tracked, larger follow-up, not attempted against 5
already-critical, already-tested modules in one pass.
