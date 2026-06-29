# Testing the Multi-Person Perception Upgrade

## Strategy

Three layers, consistent with this project's existing test conventions
(deterministic, hardware-free, injectable clocks, no `sleep()`-based timing):

1. **Per-package unit tests** — each new/extended package's `core/` modules
   are pure Python with zero rclpy dependency, tested in isolation.
2. **Per-package integration tests** — realistic multi-cycle scenarios within
   one package (e.g. `bonbon_multi_person_tracker/tests/integration/`).
3. **Cross-package scenario suite** —
   [`tests/scenarios/test_multi_person_perception_scenarios.py`](../tests/scenarios/test_multi_person_perception_scenarios.py)
   at the repo root, composing the REAL core classes from all 6 packages
   together the same way the ROS2 nodes wire them. A `conftest.py` puts each
   package on `sys.path` since ament_python packages don't share imports by
   default.

No package's tests require rclpy or a sourced ROS2 workspace — they run via
the existing `scripts/test.sh --no-ros2` gate (the same one CI calls), with
the scenario suite added as the final step.

## Test counts by package

| Package | New tests | Notable coverage |
|---|---|---|
| `bonbon_object_intelligence` | 36 | permanence lifecycle, calibration, OCR hook, memory hook, depth association |
| `bonbon_multi_person_tracker` | 76 | lifecycle FSM, identity association, scene manager, integration scenarios |
| `bonbon_gesture` (extension) | 47 | person assignment, body-part classification, temporal stability (2 modules had zero prior unit tests) |
| `bonbon_speaker_intelligence` | 76 | identity continuity, transcript segmentation, AV association, voice emotion cache, turn builder |
| `bonbon_human_state_fusion` | 64 | active speaker tracking, urgency/engagement, evidence summary, confidence calculation, fusion engine |
| `bonbon_behavior_engine` (extension) | 47 | 10 behavior rules + focus selection + child-safety modifier (35) + `ProposalEvaluator` regression suite (12, see below) |
| Cross-package scenarios | 25 | all 25 named scenarios from the project brief |

## The 25 scenarios

See [`tests/scenarios/test_multi_person_perception_scenarios.py`](../tests/scenarios/test_multi_person_perception_scenarios.py)
for the full list with purpose/setup/input/expected/safety-relevance per
scenario, matching this project's established scenario-test format. Grouped:

- **1–3**: object detection, occlusion tracking, confidence rejection
- **4–7**: multi-person detection, departure, arrival, reappearance
- **8–9**: known/unknown face handling
- **10–13**: gesture-to-person linkage, safety gestures, pointing, simultaneous multi-person gestures
- **14–18**: two-speaker diarization, AV association, off-camera speaker, overlapping speech, noisy audio
- **19–20**: speaking-status lifecycle (start/stop)
- **21–23**: per-person emotion isolation, active-speaker focus, identity-mixing prevention
- **24–25**: the two pre-existing control invariants (LLM never directly acts; Safety Supervisor blocks unsafe actions)

## A real safety gap found by this test suite

Writing scenario 25 ("Safety Supervisor blocks unsafe action") caught a
genuine, narrow gap: `ProposalEvaluator` rejected `navigate`/`approach`
proposals at DANGER level but **not** `gesture` — even though
`SafetyState.msg` documents DANGER as "imminent hazard, ALL motion
stopped." A downstream `ActuationSafetyGate` priority threshold happened
to still block the actual servo movement (defense-in-depth caught it), but
the evaluator's own decision was misleading, and the system was relying on
a single downstream layer rather than every layer being independently
correct.

**Fixed**: `gesture` is now rejected alongside `navigate`/`approach` at
DANGER level. A dedicated
[`test_proposal_evaluator.py`](../ros2_ws/src/bonbon_behavior_engine/tests/test_proposal_evaluator.py)
was added — this class had zero direct unit tests before (only indirect
coverage via `tests/integration/test_behavior_integration.py`).

This is the kind of finding the cross-package scenario suite is specifically
designed to catch: a gap that's invisible to any single package's unit
tests (each layer in isolation looked fine) but visible once the full
decision chain is exercised end-to-end.

## Running the tests

```bash
# Everything (the CI gate)
bash scripts/test.sh --no-ros2

# Just the cross-package scenarios
python -m pytest tests/scenarios -q

# One package
cd ros2_ws/src/bonbon_human_state_fusion && python -m pytest tests/ -q
```

## What is intentionally NOT tested here

- **Real ML model accuracy** (gesture classifier precision, STT word-error
  rate, face recognition accuracy) — this project has no labeled evaluation
  datasets; that's a separate ML-evaluation concern, not a software-test
  concern.
- **Actual hardware behavior** (camera/mic drivers) — covered by each
  driver's own mock-vs-real backend tests in `bonbon_hal`.
- **Full ROS2 node wiring** (topic names, QoS, lifecycle transitions) — the
  nodes themselves require rclpy and are exercised by the simulation smoke
  test (`scripts/simulation_smoke_test.sh`), not this suite.
