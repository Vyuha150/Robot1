# Scenario Variation Generator

How `tests/scenarios/scenario_generator.py` turns 15 declared families into
459 concrete, individually-IDed scenarios — and how to grow that number
without writing a single new test function.

## The pipeline

```
tests/scenarios/scenario_schema.py     Scenario / InputConditions dataclasses,
                                        RiskLevel / MockStrategy / HardwareRequirement
        |
tests/scenarios/scenario_catalog.yaml  variables: {environment, lighting, people,
                                        gesture, speech, robot_state, sensor} (the
                                        shared axis values) + families: [15 entries,
                                        each declaring which axes it varies, a cap,
                                        and {expected_behavior, required_safety_response,
                                        dashboard_update, pass_criteria, fail_criteria}
                                        templates]
        v
tests/scenarios/scenario_generator.py  generate_family(): cartesian product of just
                                        the declared axes -> deterministic stride-
                                        sample down to max_scenarios -> build each
                                        Scenario, formatting the templates with the
                                        combo's values
        v
tests/scenarios/generated_scenarios/<family>.yaml   one file per family + MANIFEST.yaml
```

## Why cartesian-product-then-sample, not full combinatorial

The full cross product of all 7 shared axes is 9×5×10×10×9×8×8 ≈ 2.6
million combinations — intractable and mostly redundant (most families
don't care about `environment` at all). Each family instead declares only
the 2-4 axes it actually varies (e.g. `gesture_understanding` varies
`people`, `lighting`, `gesture`, `robot_state`; everything else stays at
`scenario_schema.DEFAULT_AXIS_VALUE`). That product is still taken in
full, then `_stride_sample()` deterministically picks up to `max_scenarios`
evenly-spaced combinations — deterministic so regenerating the catalog
never produces a different set of IDs from the same YAML, and reproducible
across machines/CI runs.

## Scenario IDs

`BB-<FAMILY_CODE>-<token>-<token>-...-<NNN>`, e.g.
`BB-GEST-MP-LOWLIGHT-STOPPALM-NAV-014`. Tokens come from
`_ABBREVIATIONS`, a lookup table covering every enumerated value in the
catalog (with multi-person values — `two_people`/`five_people`/`crowd` —
deliberately collapsing to the shared `MP` token, matching the brief's
`BB-HRI-MP-LOWLIGHT-STOPPALM-001` example pattern). Unmapped values
(future catalog additions) fall back to a generic slug rather than
erroring, so the generator never breaks on a new axis value.

## What's in each generated scenario

Every entry in `generated_scenarios/<family>.yaml` has exactly the 9
fields the brief requires: `scenario_id`, `category`, `input_conditions`,
`expected_behavior`, `required_safety_response`, `dashboard_update`,
`pass_criteria`/`fail_criteria`, `mock_strategy`, `hardware_requirement`,
`metrics_to_capture`. The behavior/safety/dashboard/pass/fail text comes
from the family's YAML templates, formatted with that scenario's actual
combo values — so two scenarios in the same family read differently and
specifically, not as a generic boilerplate restatement.

## Growing the catalog

Coverage grows in the YAML, not in Python:

- **Widen an existing axis**: add a value to `variables` in
  `scenario_catalog.yaml` (e.g. a new `environment`) — every family that
  varies that axis picks it up on the next `scenario_generator.py` run.
- **Add a new axis to a family**: add it to that family's `axes` block
  (and, if family-specific, it lands in `InputConditions.extra` rather
  than the 7 shared fields — see `boot_and_deployment_topology`'s
  `boot_mode`/`topology` axes for the pattern).
- **Add a new family**: a new entry in `families:` plus a corresponding
  `tests/production/test_<family>_scenarios.py` is the entire Phase 2→4
  loop; no schema change needed.
- **Add a field-derived family member**: this happens automatically via
  `bonbon_field_learning.regression_test_generator` — see
  [FIELD_LEARNING_LOOP.md](FIELD_LEARNING_LOOP.md).

## Commands

```bash
# regenerate everything (council deterministic; same YAML -> same IDs)
python tests/scenarios/scenario_generator.py

# regenerate a single family while iterating on its catalog entry
python tests/scenarios/scenario_generator.py --family gesture_understanding

# load a family's generated scenarios from Python (what every
# tests/production/test_*_scenarios.py file does)
python -c "from scenario_generator import load_generated; print(len(load_generated('gesture_understanding')))"
```
