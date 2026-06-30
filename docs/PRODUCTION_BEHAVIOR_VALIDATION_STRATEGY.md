# Production Behavior Validation Strategy

## Why 100 fixed tests are not enough

A fixed test list checks 100 points in an effectively infinite behavior
space (environment × lighting × people × gesture × speech × robot-state ×
sensor-health, see [SCENARIO_FAMILIES.md](SCENARIO_FAMILIES.md)). It catches
regressions on exactly the paths someone already thought of, and it goes
stale the moment a new environment or failure mode shows up in the field.
It also can't grow: every new edge case the team learns about has to be
hand-typed as a 101st test, forever.

This framework replaces "100 fixed tests" with three things that compound
instead of merely accumulating:

1. **Scenario families** (15, this directory) — bounded variable sets, not
   individual cases.
2. **A generator** (Phase 2) that expands a family into hundreds of
   concrete, individually-IDed scenarios by combinatorial sampling, so
   coverage grows by widening the catalog, not by hand-writing tests.
3. **A field learning loop** (Phase 6) that turns every real-world failure
   into exactly one new regression scenario, so the catalog grows from
   reality, not just imagination.

## Architecture

```
docs/SCENARIO_FAMILIES.md                 <- 15 families, the variable space
        |
tests/scenarios/scenario_catalog.yaml     <- which variables, which families
        v
tests/scenarios/scenario_generator.py     <- combinatorial expansion
        v
tests/scenarios/generated_scenarios/*.yaml  <- concrete, IDed scenarios
        v
tests/production/test_*_scenarios.py      <- loads scenarios, drives the
        |                                     real module under test
        v
bonbon_behavior_validation/behavior_oracle.py  <- judges the outcome
        |
        +-- safety / dashboard / perception / speech / navigation assertions
        v
   pass / fail per scenario
        |
        +---------------------------------------------+
        v                                              v
bonbon_behavior_validation/production_score.py   bonbon_field_learning/*
  (15 metrics -> weighted score -> PASS/FAIL gate)  (failures -> regression
        |                                             tests, dataset version,
        v                                             model eval)
  dashboard /validation/production-score
```

## CI-safe vs. hardware-gated, precisely

A scenario is **CI-safe** when every variable in it can be satisfied by an
injected fixture, a mock, or a simulation replay — no physical sensor,
actuator, or accelerator is read. It runs in every CI job, on every commit,
with `pytest -m "not hardware_gated"`.

A scenario is **hardware-gated** when correctness depends on something only
real hardware can prove: timing under real thermal load, true Hailo
inference, a physical e-stop button, a live microphone array. These carry
`hardware_gated` plus the specific gate (`pi_gated`, `ai_hat_gated`,
`safety`). They are written so that:

- off the named hardware, the test **SKIPs** with a stated BLOCKED reason
  (never silently passes, never silently disappears from the report),
- on the named hardware (detected the same way `bonbon_ai_runtime`'s
  `test_hardware_gated.py` already does — a real detector, opt-in env var),
  the test actually runs and must actually pass.

`production_score.py` reports BLOCKED scenarios as their own bucket — they
never count toward "passed" and never silently inflate the readiness score.

## Simulation's role

Simulation (`bonbon_simulation`) sits between mocks and hardware: it
exercises real planner/controller/behavior-engine code against a physics or
scripted-event harness instead of a single function call, and against
recorded/public sensor data instead of fixtures. It's the primary surface
for families 6 (navigation), 10 (speech/diarization against recorded audio),
and 15 (replaying synthetic failure streams). Simulation tests are CI-safe
(`simulation` marker) — they don't require the Pi or the HAT — but they are
slower and run on a schedule/PR-label rather than every commit, matching the
existing `bonbon_simulation` package's role in this repo.

## From failure to regression test

1. The Behavior Oracle marks a scenario outcome `FAIL` or `UNCERTAIN`.
2. `bonbon_field_learning.failure_case_logger` writes an anonymized event
   (category, scenario context, oracle reason — never raw face/audio unless
   debug mode was explicitly on for that session).
3. The event lands in `human_review_queue`; a human labels the correct
   expected outcome.
4. `regression_test_generator` turns the labeled case into a new entry in
   `tests/scenarios/generated_scenarios/` with a fresh scenario ID and adds
   it to the relevant family's pytest file — so it is asserted on every
   future run, not just remembered in a ticket.
5. `dataset_version_manager` bumps the dataset version; `model_evaluation_tracker`
   re-scores the model against the new + existing regression set and blocks
   deployment if the regression pass rate drops.

This is the actual "behavior improves over time" mechanism: the catalog of
regression scenarios only grows, and every deployment is checked against all
of it, automatically.

## Online data's role (summary; full detail in `ONLINE_DATASET_STRATEGY.md`)

Public datasets bootstrap base capability per category (object/person
detection, pose/gesture, ASR, diarization, emotion, navigation). They cannot
solve BonBon-specific distribution shift (this robot's cameras, this
microphone array, this corridor width, this accent mix) — that requires
BonBon's own environment data and, fastest of all, its own failure cases.
Public data trains/fine-tunes models; BonBon field data validates and
specializes them. Emotion signals (voice and face) are always treated as
uncertain (family 11) regardless of data source.

## Privacy by construction

Raw face imagery and raw audio are **never** written to the default event
store. `anonymized_event_store.py` only accepts records that have passed
through a schema that has no raw-media fields; raw snapshots can only reach
disk through a separate, explicitly-enabled debug path
(`PRIVACY_SAFE_DATA_COLLECTION.md` specifies the exact toggle and retention
rule). This is enforced by a test, not a comment: every event-store test
asserts the absence of biometric byte fields in the default path.

## Production readiness gate

`production_score.py` computes a weighted score (safety 30% / reliability
20% / perception 15% / HRI 15% / edge 10% / dashboard 5% / maintainability
5%) **and** a hard gate: if the safety sub-score is below its threshold, the
overall verdict is `FAIL` regardless of the weighted total. A robot cannot
buy its way to "production ready" with good navigation scores while safety
is broken.

## Commands

```bash
# generate (or regenerate) the scenario catalog
python tests/scenarios/scenario_generator.py --catalog tests/scenarios/scenario_catalog.yaml \
  --out tests/scenarios/generated_scenarios

# CI-safe run (everything except hardware_gated)
python -m pytest tests/production -m "not hardware_gated" -q

# a single family
python -m pytest tests/production/test_safety_scenarios.py -m safety -q

# hardware-gated, on a real Pi + AI HAT only
BONBON_HAILO_HW_TEST=1 python -m pytest tests/production -m hardware_gated -q

# production readiness score
python -m bonbon_behavior_validation.production_score --report
```
