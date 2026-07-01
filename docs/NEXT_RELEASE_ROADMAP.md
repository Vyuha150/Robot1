# Next Release Roadmap

Everything here is explicitly **POST-RELEASE** — out of scope for this
release candidate per [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md).
Nothing in this document should be started until the current release is
validated on real hardware (see
[FINAL_PRODUCTION_READINESS_CHECKLIST.md](FINAL_PRODUCTION_READINESS_CHECKLIST.md)'s
BLOCKED rows).

## Priority 1 — closes the two biggest remaining gaps

1. **`bonbon_vision._build_detector()` → `RuntimeSelector` wiring.** The
   Hailo/CPU/TensorRT/Mock runtime abstraction is proven at the unit level
   (30 tests); the live vision node still constructs its own detector
   directly. This is the single highest-leverage next step for the AI HAT
   blocker to be fully closed end-to-end, not just at the abstraction
   layer.
2. **Software-triggered `emergency_stop`.** Currently hardware/GPIO only.
   A software e-stop path (dashboard-triggered, still gated through the
   real Safety Supervisor state machine, never bypassing it) is the
   highest-value of the 7 unimplemented dashboard commands.
3. **Physical validation pass.** Every `BLOCKED` row in the final
   checklist, run on a real Pi 5 + AI HAT: boot-topology live confirmation,
   Hailo inference benchmark, e-stop latency under full AI load, thermal/
   CPU stability, sensor unplug/replug, multi-person/gesture/speech
   accuracy in a real room.

## Priority 2 — remaining dashboard commands

`pause`, `resume`, `restart_module`, `get_config`, `set_config`,
`memory_query`, and `rag_query` (needs `LLMQuery.srv` to actually be
served by `bonbon_llm` — the service is defined but has no server today).

## Priority 3 — modular-mode decomposition

Finer-grained modular-Pi service decomposition: vision/gesture/affective/
speaker as independent systemd services rather than bundled under
`bonbon-perception`. Would let a Pi deployment run only the perception
sub-capabilities it actually needs, at the cost of more services to keep
mutually consistent — worth doing once the coarser modular mode has real
field hours behind it.

## Priority 4 — test infrastructure

- Real-ROS2 CI coverage for the 20 packages currently only exercised via
  rclpy-stub pure-Python tests (closes `ci_coverage_gap`).
- Investigate `bonbon_operator_api`'s slow test suite (1-4 min vs <2s
  elsewhere) — likely real sleeps/network waits in WebSocket tests.

## Explicitly not planned (would need a product decision first)

- New scenario families beyond the frozen 15.
- New ROS2 packages beyond the frozen 27.
- Any change to the Safety Supervisor singleton policy or the LLM-never-
  acts-directly guarantee — these are architectural invariants, not
  incremental features.

## How an item graduates from this roadmap into a release

1. Update [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md) in the same
   change that starts the work (move it out of POST-RELEASE).
2. Add or extend the relevant scenario family
   ([SCENARIO_FAMILIES.md](SCENARIO_FAMILIES.md)) and generated scenarios
   if it changes observable behavior.
3. Ship tests, config, docs, and dashboard visibility together — the same
   rule this finalization pass followed for every fix.
