# Edge AI Safety Mechanism Audit

GAP-E5 (docs/EDGE_AI_GAP_ANALYSIS.md): "safety enforcement is scattered
across 5-6 independently coded mechanisms with inconsistent fail-open/
fail-closed defaults." This doc is the systematic audit that gap named as
missing — every mechanism's actual default/stale/error behavior, checked
against real code, not assumed.

## The 6 mechanisms

| # | Mechanism | File | Default/stale behavior | Verdict |
|---|---|---|---|---|
| 1 | `CommandAuthorizer` / `SafetySnapshot.safe_default()` | `bonbon_llm/safety/authorization.py` | Fixed this session (GAP-E1): navigation/actuation both `False`, `state_id=SAFETY_INITIALIZING` before first message or when the safety message is >2s stale | **FAIL-CLOSED** |
| 2 | `MotionApprovalGateway` | `bonbon_motion_approval_gateway/core/approval_gateway.py` | Unrecognized `proposal_type` → rejected; `requires_manual_reset` → rejects everything except `alert_operator`/`ignore` | **FAIL-CLOSED** |
| 3 | `safety_gate_node` | `bonbon_safety/nodes/safety_gate_node.py` | `_can_actuate()`/`_can_navigate()` return `False` when `self._safety_state is None` (line ~442) or `_supervisor_ok is False`; watchdog staleness (line ~508) sets `_supervisor_ok=False` and zeroes velocity | **FAIL-CLOSED** |
| 4 | `SafetyStopBridge` | `bonbon_navigation/safety/safety_stop_bridge.py` | Initial state `SAFETY_INITIALIZING`, `_nav_permitted=False` (line ~108); `is_motion_blocked` returns `True` before the first message (age check against `_last_update=0.0` always exceeds the watchdog window) | **FAIL-CLOSED** |
| 5 | `SafetyCommandFilter` | `bonbon_llm/safety/command_filter.py` | Empty/no-match text → `SAFE` (by design — empty text is genuinely safe); **internal errors previously propagated uncaught** rather than defaulting to `BLOCKED` | Was **FAIL-OPEN on internal error** — **fixed this pass**, see below |
| 6 | `CommandRiskClassifier` / `ProposalEvaluator` | `bonbon_behavior_engine/core/{command_risk_classifier,proposal_evaluator}.py` | Empty/unrecognized command text → `recommended_action="approve"` by explicit default fallthrough; `CommandRiskClassifier` is only invoked at all when `source == "llm"` — gesture/speech-intent-sourced proposals never got real content-risk screening | **FAIL-OPEN by design** — mitigated this pass, see below |

## What was fixed this pass

**Mechanism 5 (`SafetyCommandFilter`)**: `filter_text()` now wraps its
scan in a try/except — any internal error (a malformed pattern, an
unexpected input type) returns `FilterStatus.BLOCKED` deterministically
instead of letting an exception propagate to a caller that might not
handle it safely. This was the one mechanism whose fail-open behavior was
a genuine oversight (not a documented design choice) — the method's own
docstring says "escalate to RISKY, not BLOCKED" for *content* judgment
calls, which never applied to "the filter itself broke." Regression
test: `tests/test_command_filter.py::TestInternalErrorFailsClosed`.

**Mechanism 6 (`CommandRiskClassifier`/`ProposalEvaluator`)**: not
changed directly — "unrecognized command → approve" is a considered,
heavily-tested design choice (`tests/test_proposal_evaluator.py`,
`tests/test_command_risk_classifier.py`), and CommandRiskClassifier only
applying to `source=="llm"` proposals is itself intentional (see
`ProposalEvaluator.evaluate()`). Rather than force a breaking behavioral
change into that module, **Finding 8's fix** (see
[`EDGE_AI_SAFETY_SEPARATION_FINAL_REPORT.md`](EDGE_AI_SAFETY_SEPARATION_FINAL_REPORT.md))
adds `SafetySeparationGuard` as an *independent, additional* check in
`behavior_engine_node._dispatch_proposal()` — covering exactly the gap
this fail-open default left: gesture/speech-sourced proposals (which
`CommandRiskClassifier` never screened at all) now also get a real
content-risk check (medical-diagnosis-sounding text, leaked privacy
fields) before dispatch, and any gesture actuation still passes through
the real, tested, fail-closed `ActuationSafetyGate`
(`bonbon_actuation/core/actuation_safety_gate.py`) downstream regardless.

## Why this isn't a full unification (and why that's the right call here)

Retrofitting all 6 mechanisms to route through one shared
`SafetySeparationGuard` authority would be the "complete" fix GAP-E5's
own wording gestures at ("safety enforcement is scattered ... structural
reason GAP-E1 was possible"). That is a genuine architectural change
touching every safety-relevant node in the repo, each with its own
mature, independently-tested behavior. This pass instead:

1. Audited all 6 with real evidence (this document) — previously no
   single place had this.
2. Fixed the one mechanism whose fail-open behavior was an unintentional
   gap (`SafetyCommandFilter`'s error handling).
3. Added `SafetySeparationGuard` as a new, independent, defense-in-depth
   layer at the two points GAP-E1/E2/Finding-8 identified as having the
   weakest existing coverage (`llm_orchestrator_node`'s rule-engine
   stage, `behavior_engine_node`'s gesture/speech dispatch) — without
   removing or bypassing any of the 6 mechanisms' own checks.

`SafetySeparationGuard` now sits ALONGSIDE these 6 mechanisms as a 7th,
shared, always-fail-closed reference point every new caller can consult
— per its own docstring, "not a replacement for any of them ... gives
every one of them (and every future caller) ONE place to ask." Retrofitting
the existing 6 to route through it exclusively remains open (still
tracked, not silently dropped) as a larger, deliberate follow-up rather
than a rushed change to 5 already-safety-critical, already-tested modules
in one pass.
