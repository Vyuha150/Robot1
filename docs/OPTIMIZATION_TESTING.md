# Optimization Testing

Covers the full test inventory added across this round's 6 phases (audit
fixes through scenario tests) and how to run all of it.

## Test inventory

| Phase | Package / file | New tests |
|---|---|---|
| 1 — audit fixes | `bonbon_safety` (existing suites re-verified, none new) | 0 |
| 2 — perception efficiency | `bonbon_perception_efficiency/tests/` (9 core modules) | 70 |
| 3 — data feedback | `bonbon_data_feedback/tests/` (7 core modules) | 55 |
| 4 — runtime optimization | `bonbon_affective_ai/tests/test_affective_node.py::TestAffectiveNodeBackpressure` | 4 |
| 4 — runtime optimization | `bonbon_llm/tests/test_response_cache.py` | 15 |
| 5 — perf benchmarks | `bonbon_safety/tests/benchmarks/bench_hotpaths.py` + `test_perf_targets.py` | 2 new (17 total in those two files) |
| 6 — named scenarios | `tests/scenarios/test_efficiency_and_feedback_scenarios.py` | 16 |
| **Total new** | | **162** |

Every number above was independently re-counted via `pytest -q` immediately
before writing this document — not carried over from memory.

## Running everything

```bash
# Fast gate — pure Python, no ROS2/hardware (what CI runs)
bash scripts/test.sh --no-ros2

# Latency benchmarks specifically
cd ros2_ws/src/bonbon_safety && python tests/benchmarks/bench_hotpaths.py
```

`scripts/test.sh --no-ros2` now also runs `bonbon_llm` (253 tests, not
previously in the gate — added this round since it was confirmed fully
pure-Python and rclpy-independent) in addition to every package the prior
multi-person engagement already gated.

## What each phase's tests actually verify

- **Phase 2** (`bonbon_perception_efficiency`): every one of the 9 core
  classes' decision logic in isolation — hysteresis behavior
  (`LoadSheddingController`), sustained-vs-transient degradation
  (`DegradedModeManager`), floor-clamping (`ConfidencePolicyManager`),
  focus-weight assignment (`ActivePersonFocusManager`), plus the
  orchestrator's combination logic (`PerceptionBudgetManager`).
- **Phase 3** (`bonbon_data_feedback`): privacy gating (raw snapshot
  refusal, forbidden-key stripping — tested both with and without debug
  mode), the hard-negative classification boundary, batch-insert
  correctness, retention deletion scoped correctly to category — all
  against a real temp-file SQLite database, not a mock.
- **Phase 4**: the `BoundedInferenceQueue` wiring inside
  `affective_ai_node` specifically (admit-until-full, reject-when-full,
  free-on-complete, queues independent of each other) — verifying the
  *integration*, since the queue class itself already has 10 tests in
  Phase 2. The `ResponseCache`'s safety properties: never caches
  llm_error/safety_block/hallucination, context-sensitive keying, TTL
  expiry, LRU eviction.
- **Phase 5**: the two new latency budgets pass as both a standalone
  benchmark script and a pytest-collected latency assertion (the same dual
  mode every other budget in the catalogue uses).
- **Phase 6**: the 15 named scenarios, each composing real classes across
  package boundaries the way a deployed system would — not unit tests of
  one function, narrative scenarios with documented purpose/safety
  relevance, following the exact convention established by
  `test_multi_person_perception_scenarios.py`.

## What was deliberately NOT re-tested

Every package's pre-existing test suite was re-run after each change to
confirm no regression (`bonbon_data_stores`: 108 passed; `bonbon_bringup`:
6 passed; `bonbon_vision`: the one file that imports the changed code,
`test_vision_node.py`, 29 passed) — but none of those pre-existing tests
were modified beyond the minimum needed to keep collecting (one stub
addition each in `test_vision_node.py` and `bonbon_data_stores`'
`SchemaMigrator` extension, both backward compatible).

## A note on scope discipline during this work

Running `ruff check --fix` once swept unrelated typing-modernization
changes (`Optional[X]` → `X | None`, `Dict`/`List` → `dict`/`list`) across
entire pre-existing files purely because one new line needed an import
sorted. Those files were reverted to `HEAD` and the intended edits
reapplied surgically, file by file, confirmed via `git diff --stat` to
contain only the intended change before being committed. This is mentioned
here because it is exactly the kind of unintended scope creep automated
tooling can introduce, and the discipline of checking every diff before
committing is what caught it.

## Known, pre-existing, NOT introduced or worsened by this round

`bonbon_vision/tests/test_frame_throttler.py` hangs in isolation — confirmed
to reproduce on a file untouched by any change in this round (flagged
earlier in the same working session, attributable to separate, unrelated,
uncommitted work in `bonbon_vision`/`bonbon_speech`). `bonbon_vision` is
intentionally not part of `scripts/test.sh --no-ros2`'s gate for this
reason; only `test_vision_node.py` (the file this round's vision_node.py
change actually touches) was run directly, with a timeout, and passes
cleanly.
