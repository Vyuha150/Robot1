# Safety Separation Audit

Edge AI Runtime brief, Phase 1. This is the most consequential of the five
audit docs — it found real, concrete gaps against the brief's rule 2
("LLM must never directly control navigation, motors, servos, or
emergency stop") and rule 6 ("Safety Supervisor must approve movement
and actuation"), not just architectural duplication. Every finding below
is grounded in a specific file/line, traced by following actual ROS2
topic publishers/subscribers, not inferred from docstrings or config
intent.

## Verdict: rule 2/6 is PARTIALLY enforced, with one UNSAFE path

Servo/stepper actuation is genuinely safe — single-writer tracing shows
no bypass. **Nav2 goal dispatch is not** — an LLM-originated message can
reach a real `BasicNavigator.goToPose()` call through a fail-open check
that never touches the one component designed to be the sole approval
authority.

## Finding 1 (UNSAFE): LLM can trigger a real Nav2 goal via a fail-open path

- `bonbon_llm/bonbon_llm/nodes/llm_orchestrator_node.py::_dispatch_behavior`
  publishes `BehaviorRecommendation` directly to `/perception/behavior`.
- `bonbon_navigation/bonbon_navigation/nodes/navigation_node.py::_on_behavior_recommendation`
  subscribes to that exact topic and, for `navigate_to_goal`/
  `approach_person`/`serve_item`, checks only a locally-cached
  `is_motion_blocked` flag before calling `self._goal_manager.enqueue(...)`,
  which a 10Hz loop turns into a real `BasicNavigator.goToPose()` call.
- The safety check the LLM path actually goes through is
  `bonbon_llm/bonbon_llm/safety/authorization.py::CommandAuthorizer`, a
  **second, independent** authorizer from the one designed for this —
  `bonbon_motion_approval_gateway`. Its `SafetySnapshot.safe_default()`
  (lines 108-116) is explicitly documented as the state used "before
  first SafetyState message arrives" and returns
  `actuation_permitted=True, navigation_permitted=True` — **fail-open**.
- This directly contradicts `bonbon_motion_approval_gateway`'s own
  `_fail_closed_context()`, which returns `actuation_permitted=False` in
  the equivalent situation. Two LLM-adjacent safety gates exist with
  **opposite fail-safe postures**, and the fail-open one is the one
  actually in the LLM's real dispatch path.
- **This is the concrete violation of rule 2** the brief anticipated:
  under a specific timing condition (early after boot, before the first
  real `SafetyState` message), an LLM behavior recommendation can reach
  Nav2 goal dispatch without the Safety Supervisor's approval.

## Finding 2 (design gap): the propose/approve pipeline is disconnected from execution

- `bonbon_motion_approval_gateway` is real, well-designed, and does
  exactly what rule 6 asks — evaluates `BehaviorProposal` against live
  `SafetyState`, publishes `BehaviorDecision` to
  `/bonbon/motion/approved_command`.
- **Nothing subscribes to `/bonbon/motion/approved_command`.** Confirmed
  by repo-wide grep: only the gateway's own publisher and
  `bonbon_operator_api`'s dashboard bridge (read-only, decision-only, not
  command content) reference that topic.
- Net effect: the one component architected to be the central safety
  separation boundary is currently **audit/logging-only**. Real
  actuation reaches hardware through a *different*, working path
  (`bonbon_actuation` → `safety_gate_node`, confirmed safe — see Finding
  4) that never consults this gateway at all.
- This is exactly the gap Phase 7's `safety_separation_guard.py` should
  close — not by building a third gate, but by making the existing
  gateway's decision the thing that actually gates dispatch.

## Finding 3 (design gap): safety enforcement is scattered across 5-6 independent mechanisms with inconsistent defaults

No single `SafetySeparationGuard`-equivalent class exists. What's there
instead, each independently coded:

1. `bonbon_safety/nodes/safety_gate_node.py` — topic-level actuation/
   velocity gate. Fail-closed watchdog (blocks after 2s of no supervisor
   heartbeat). **This one is solid.**
2. `bonbon_motion_approval_gateway/core/approval_gateway.py` — proposal
   evaluator, fail-closed default, but disconnected from execution
   (Finding 2).
3. `bonbon_behavior_engine`'s `command_risk_classifier.py` +
   `llm_command_gate.py` + `proposal_evaluator.py` — text/intent risk
   classification before publishing proposals.
4. `bonbon_llm/safety/command_filter.py` (`SafetyCommandFilter`) —
   regex/pattern filter on raw LLM output text.
5. `bonbon_llm/safety/authorization.py` (`CommandAuthorizer`) — the
   fail-open authorizer from Finding 1.
6. `bonbon_navigation/safety/safety_stop_bridge.py` — a third,
   navigation-specific velocity-state gate.

`config/distributed/pi_navigation_safety.yaml` (lines 88-98) *states the
intent* that Pi-3's safety supervisor + `bonbon_motion_approval_gateway`
is the only allowed path — the code does not currently realize that
intent.

## Finding 4 (confirmed safe): servo/stepper actuation has no bypass

Single-writer tracing confirms this path is genuinely safe today:
`bonbon_actuation/nodes/actuation_node.py` is the sole publisher to the
`_raw` command topics (`/bonbon/servo/*/command_raw`,
`/bonbon/stepper/command_raw`) that feed `safety_gate_node`, which is the
sole publisher to the gated `…/command` topics, which
`bonbon_hal`'s `servo_node.py`/`stepper_node.py` are the only subscribers
to. No other publisher to any `_raw` topic exists anywhere in the repo
(repo-wide grep). UI packages (`bonbon_operator_api`, `bonbon_patient_kiosk`)
have zero references to any of these topics — they cannot reach
actuation directly today.

## Finding 5 (broken, not enforced): Nav2→wheel-motor velocity path is dead code

- `safety_gate_node` subscribes to `/bonbon/cmd_vel_raw`.
- `navigation_node`'s own docstring and `SafetyStopBridge`'s docstring
  both claim velocity publishes to `/bonbon/safety_gate/cmd_vel` — a
  **different topic name**, with no remap anywhere connecting the two.
- Worse: `navigation_node._publish_gated_vel` builds a `Twist` message
  and **never calls `.publish()`** — no publisher for that topic is even
  created in `_create_publishers`.
- Net effect: Nav2-driven wheel velocity currently cannot reach the
  motors at all. It is safe only because it is broken, not because it is
  gated — this needs fixing as real functionality, and the fix must go
  through the safety gate correctly the first time, not reintroduce
  Finding 1's problem for velocity instead of goals.

## Finding 6 (honesty gap): Navigation Pi's cross-Pi heartbeat doesn't reflect real component health

- `bonbon_distributed_safety/nodes/distributed_safety_node.py::_cb_publish_heartbeat`
  publishes `status = 0 # OK` unconditionally — a hardcoded liveness
  ping from the process itself, not an aggregate of
  `bonbon_safety.watchdog_node`'s `critical_node_crashed`/
  `important_node_crashed` flags.
- A crashed `safety_gate_node` or `navigation_node` on Pi-3 would **not**
  be reflected in the heartbeat Pi-1/Pi-2 observe — only "is the
  heartbeat process itself alive," not "are Pi-3's safety-critical nodes
  actually healthy."
- This matters for rule 10 ("dashboard must show real ... safety
  blocks") and the brief's "board heartbeat" priority-1 scheduling item
  — the heartbeat currently can say healthy while it isn't.

## Finding 7 (test gap): no test exercises the real topic graph

`tests/llm_local/test_qwen_safety.py` verifies `SafetyCommandFilter`
(text-pattern matching) and confirms the LLM model registry schema has
no actuation-authority field — real, useful, but narrow. `tests/safety/`
is an **empty directory**. No existing test publishes a
`BehaviorRecommendation` and asserts it does/doesn't reach
`BasicNavigator.goToPose()`; none catches the Finding 5 topic-name
mismatch; none asserts a UI package can't reach a motor topic against
the real ROS2 graph. All of Phase 7's 8 required safety-separation tests
must exercise real message flow, not just text filtering, to actually
prove what the brief asks them to prove.

## Update: Findings 1, 2, and 5 fixed

At the user's explicit direction, GAP-E1 (Finding 1) was fixed
immediately, and GAP-E2/E5 (Findings 2 and 5) were fixed as part of the
Phase 7 follow-up. See `docs/EDGE_AI_GAP_ANALYSIS.md` for the full fix
description and test evidence. Findings 3, 4, 6, and 7 remain open --
full centralization of the scattered safety mechanisms (Finding 3) is a
larger consolidation effort intentionally not attempted in this pass,
and Finding 6 (Pi-3 heartbeat honesty) and Finding 4 (confirmed-safe
actuation path) are unaffected by these fixes.

## New finding discovered while fixing GAP-E2 (not yet fixed)

**Finding 8 — `bonbon_behavior_engine`'s own proposal pipeline also
bypasses the gateway, via a fourth independent evaluator.**
`behavior_engine_node.py`'s `_dispatch_proposal()` method -- the path
`_on_speech_command` and the multi-person human-state handlers use for
`speak`/`gesture` actions -- evaluates via a locally-owned
`ProposalEvaluator`/`CommandRiskClassifier` pair, then directly calls
`_dispatch_tts()`/`_dispatch_actuation_gesture()` itself on approval. It
never publishes to `/bonbon/behavior/proposal` (the same dead publisher
GAP-E2 found and fixed for navigation) and never consults
`bonbon_motion_approval_gateway`. This is a fourth independent safety
evaluator (after `SafetyCommandFilter`, `CommandAuthorizer`, and
`MotionApprovalGateway`) — for `speak`/`gesture` specifically, not
navigation. Since `_dispatch_proposal` has no handler branch for
`navigate`/`approach` action types, this does NOT affect the
navigation-goal fix above (a stray "navigate" proposal reaching this
method would simply have no effect) — but the speak/gesture path itself
still isn't unified with the rest. Flagged for a future pass, out of
scope for this one (which was specifically about closing the confirmed
UNSAFE navigation-dispatch gap, not a full consolidation of every
proposal path in the codebase).

## What Phase 7 must actually do (informed by this audit)

Not build a 4th independent gate. Instead:
1. Make `bonbon_motion_approval_gateway`'s `BehaviorDecision` the thing
   `navigation_node` and `actuation_node` actually wait on before
   dispatching — closing Finding 2.
2. Fix `CommandAuthorizer.SafetySnapshot.safe_default()` to fail closed,
   matching the gateway's own posture — closing Finding 1.
3. Reconcile the `cmd_vel_raw` vs `safety_gate/cmd_vel` naming and wire
   the actual `.publish()` call — closing Finding 5, without
   reintroducing Finding 1's problem for velocity.
4. Aggregate real component health into the Pi-3 heartbeat — closing
   Finding 6.
5. Write the 8 required tests against the real topic graph, not just
   text patterns — closing Finding 7.
6. Consolidate, don't multiply: `safety_separation_guard.py` should be a
   thin classifier (the brief's 9 action categories) that existing
   gates/filters call into for a consistent answer, not a 7th
   independent implementation.
