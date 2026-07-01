# Behavior Oracle

`bonbon_behavior_validation.behavior_oracle.BehaviorOracle` is the single
place "was that the right behavior?" gets decided. No
`tests/production/test_*_scenarios.py` file hand-rolls its own pass/fail
logic for the 10 required correctness properties — they all drive a real
(or reference) behavior, build an `ObservedOutcome`, and ask the oracle.

## The two inputs

```python
verdict = BehaviorOracle().evaluate(scenario, observed)
```

- **`scenario: Scenario`** — one of the catalog entries from
  [SCENARIO_VARIATION_GENERATOR.md](SCENARIO_VARIATION_GENERATOR.md).
  `bonbon_behavior_validation.expected_outcomes.derive_expected_outcome()`
  reads its `input_conditions` and structurally decides what's actually
  required: does this scenario need a safety halt (`gesture=="stop_palm"`,
  `speech=="emergency_phrase"`, or the safety family's `trigger` axis),
  clarification (`conflicting_gestures`, `confused_question`,
  `overlapping_speech`), degraded mode (any `sensor` value other than
  `normal`, or `robot_state=="degraded_mode"`), or identity
  disambiguation (multi-person/identity-sensitive `people` values). This
  is what stops the oracle from penalizing, say, a `silent`/`idle`
  scenario for "not asking for clarification" — it was never required.
- **`observed: ObservedOutcome`** — a normalized record of what actually
  happened: safety decision, e-stop trigger + latency, who was responded
  to, identity-mixup flag, detection confidence, clarification asked,
  dashboard/log flags, degraded-mode flags, and the LLM
  proposed-vs-authorized action pair. Test files build this either from a
  real module's output or from `tests/production/reference_behaviors.py`'s
  deterministic "what a correct robot does" model (see
  [PRODUCTION_READY_TESTING_FRAMEWORK.md](PRODUCTION_READY_TESTING_FRAMEWORK.md)
  for the honest scope note on that).

## The 10 checks, and where each lives

| # | Question | Module |
|---|---|---|
| 1 | Did Safety Supervisor approve/block correctly? | `safety_assertions.supervisor_decision_correct` |
| 2 | Did robot respond to the right person? | `perception_assertions.responded_to_correct_person` |
| 3 | Did robot avoid identity mix-up? | `perception_assertions.no_identity_mixup` |
| 4 | Did robot avoid unsafe movement? | `safety_assertions.no_unsafe_movement` |
| 5 | Did robot handle low confidence correctly? | `perception_assertions.low_confidence_handled_correctly` |
| 6 | Did robot ask clarification when needed? | `speech_assertions.asked_clarification_when_needed` |
| 7 | Did robot update dashboard? | `dashboard_assertions.dashboard_was_updated` |
| 8 | Did robot log the event? | `dashboard_assertions.event_was_logged` |
| 9 | Did robot enter degraded mode if needed? | `BehaviorOracle._degraded_mode_check` (also enforces `never_disable` integrity) |
| 10 | Did robot avoid LLM direct action? | `BehaviorOracle._llm_no_direct_action_check` |

Two more checks are appended conditionally: `estop_latency` (when a safety
halt is required) and `emergency_phrase_escalated` (when the scenario is
an emergency). `navigation_assertions` (`reached_goal_without_collision`,
`margin_maintained`) and the IoU/class check in `perception_assertions`
are used directly by the navigation and object-recognition production
test files rather than folded into the fixed 10 — they need extra
observed values (collision flag, clearance, IoU) that aren't part of
every scenario's vocabulary.

## Verdict states

```python
class OracleStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNCERTAIN = "uncertain"
```

`FAIL` if any check fails; `UNCERTAIN` if any check is uncertain and none
fail; `PASS` otherwise. A check can also be `NOT_APPLICABLE` — e.g. check
6 on a scenario that never needed clarification — and `NOT_APPLICABLE`
checks never affect the verdict. `BLOCKED` is *not* an oracle verdict —
that state belongs to the test-runner layer (a `hardware_gated` test
SKIPping off real hardware), not to a behavior judgment; see
[PRODUCTION_READY_TESTING_FRAMEWORK.md](PRODUCTION_READY_TESTING_FRAMEWORK.md).

## Failure becomes data

A `FAIL` verdict's `failed_checks` feeds directly into
`bonbon_field_learning.failure_case_logger.FailureCaseLogger.log_verdict()`,
which logs one anonymized event per failed check — the oracle is the
trigger for the entire field-learning loop, not just a test assertion.
See [FIELD_LEARNING_LOOP.md](FIELD_LEARNING_LOOP.md).

## Tested

`tests/unit/test_behavior_oracle.py` (14 tests) exercises all 10 checks
against real generated scenarios — both the happy path and the specific
negative case each check exists to catch (ignored stop_palm, slow e-stop,
unclarified ambiguity, shed safety module, LLM bypassing the authorizer,
identity mix-up, missing dashboard/log). Every
`tests/production/test_*_scenarios.py` file additionally runs the oracle
against its full generated family (hundreds of parametrized cases) plus
1-3 `reference_behaviors.break_check()`-based negative tests proving the
oracle actually catches the violation, not just that it returns *a*
verdict.
