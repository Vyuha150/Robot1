# Edge AI Safety Separation Final Report

Phase 15 summary of Phase 7's work: the most consequential phase in this
brief, covering both the new [`safety_separation_guard.py`](../ros2_ws/src/bonbon_edge_ai_runtime/bonbon_edge_ai_runtime/safety_separation_guard.py)
classifier and 3 real safety-critical bugs found and fixed
(GAP-E1, GAP-E2, GAP-E3/E5) via [`docs/SAFETY_SEPARATION_AUDIT.md`](SAFETY_SEPARATION_AUDIT.md).

## The classifier: 9 categories, one always-fail-closed answer

`SafetySeparationGuard.classify(source_module, action_type, payload)`
returns a `ClassifiedAction` with `category` (one of `TEXT_ONLY`,
`INFO_LOOKUP`, `STAFF_ALERT`, `NAVIGATION_REQUEST`, `ACTUATION_REQUEST`,
`SAFETY_CRITICAL`, `UNSAFE_DIRECT_CONTROL`, `MEDICAL_DIAGNOSIS_RISK`,
`PRIVACY_RISK`), `blocked`, `requiresApproval`, and `reason`. Per rule 13
("if unsure, degrade safely instead of failing silently"), any
unrecognized `action_type` is blocked, never default-allowed — a new
action type must be deliberately added to the classifier's tables, never
silently passed through.

## The "never allow" table — verified, not just documented

Only `{safety_supervisor, safety_gate, motion_approval_gateway}` may ever
issue a direct hardware-control action type (`direct_motor_command`,
`direct_servo_command`, `raw_nav2_goal`, `direct_navigation_command`,
`emergency_override`). Every other source — `llm`, `ui`,
`ai_pi_gesture`, `ai_pi_perception`, `behavior_engine` — attempting any of
these is `UNSAFE_DIRECT_CONTROL`, `blocked=True`, unconditionally.
Verified directly by `tests/edge_ai/test_safety_separation_guard.py::TestNeverAllowTable`
(7 tests) and 4 additional dashboard-visibility tests in
`bonbon_edge_ai_runtime/tests/test_package_integration.py`.

## Three real bugs found and fixed this pass

**GAP-E1 (fixed, before Phase 2, at the user's explicit request)**: the
LLM could reach a real Nav2 goal via a fail-open
`SafetySnapshot.safe_default()` in `bonbon_llm/safety/authorization.py` —
the *live* path `llm_orchestrator_node` actually used, bypassing
`bonbon_motion_approval_gateway` entirely. Fixed: `safe_default()` now
fails closed; the orchestrator additionally tracks safety-message
*staleness* (>2.0s falls back to fail-closed), closing a second window
the original audit hadn't separately named — the Safety Supervisor going
silent mid-operation, not just the first-boot race.

**GAP-E2 (fixed)**: `bonbon_motion_approval_gateway`'s approved
`BehaviorDecision` had zero subscribers repo-wide. Root cause: neither
`BehaviorProposal`/`BehaviorDecision` carried pose data through the
gateway's own dataclasses, and `bonbon_behavior_engine` had a
`BehaviorProposal` publisher that was wired but never called. Fixed by
threading `nav_goal_pose`/`nav_goal_label` through the gateway, adding a
new pure `behavior_recommendation_bridge.py`, and making
`navigation_node.py`'s new `_on_approved_command` handler — gated by
`should_dispatch_navigation()` — the **only** path that enqueues a Nav2
goal from AI-originated behavior.

**GAP-E3/E5 (fixed)**: the Nav2→wheel-motor velocity path was dead code —
topic-name mismatch plus a `_publish_gated_vel` that built a `Twist` and
never called `.publish()`. Fixed: the real `/bonbon/cmd_vel_raw`
publisher now exists and is actually used.

## Known open findings (documented, not fixed — out of scope for this pass)

- **GAP-E4**: Pi-3's cross-Pi heartbeat hardcodes `status = 0 # OK`
  regardless of real component health.
- **GAP-E5 (scattered mechanisms, distinct from the E3/E5 dead-code fix
  above — a pre-existing numbering collision in `EDGE_AI_GAP_ANALYSIS.md`
  flagged here for future doc hygiene)**: safety enforcement is still
  spread across 5-6 independently coded mechanisms with inconsistent
  fail-open/closed defaults — the structural reason GAP-E1 was possible.
  `SafetySeparationGuard` gives every future caller ONE place to ask, but
  does not itself retrofit the 5-6 existing mechanisms to call it.
- **GAP-E6**: no test exercises the real ROS2 topic graph for safety
  separation end-to-end (`tests/safety/` is empty).
- **Finding 8** (`SAFETY_SEPARATION_AUDIT.md`): `bonbon_behavior_engine`'s
  own `_dispatch_proposal()` uses a *fourth* independent
  `ProposalEvaluator`/`CommandRiskClassifier` pair for speak/gesture,
  bypassing the gateway too — confirmed not to interfere with the GAP-E2
  fix, but undocumented until this pass and not itself fixed.

## Verification

19 new/updated tests across 4 packages this phase
(`bonbon_motion_approval_gateway`, `bonbon_behavior_engine`,
`bonbon_navigation`, `bonbon_edge_ai_runtime`), plus 6
`tests/edge_ai/test_safety_separation_guard.py` category/never-allow/
dashboard-visibility tests. Zero regressions across the ~950-test broader
suite.
