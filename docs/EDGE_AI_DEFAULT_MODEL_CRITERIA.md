# Edge AI Default Model Criteria

Phase 14 of the Edge AI Runtime brief: the gate a candidate model/engine
must clear before it can be flipped to `enabled_by_default: true` in
[`config/models/model_registry.yaml`](../config/models/model_registry.yaml)
or [`config/edge_ai/model_registry.yaml`](../config/edge_ai/model_registry.yaml).
This formalizes, as an explicit checklist, the judgment this pass already
applied informally when the AI-model-stack and Edge-AI-Runtime work chose
each capability's current default (see
[`docs/AI_MODEL_FINAL_SELECTION_REPORT.md`](AI_MODEL_FINAL_SELECTION_REPORT.md)
and [`docs/EDGE_AI_GAP_ANALYSIS.md`](EDGE_AI_GAP_ANALYSIS.md)).

**A model may become the registry default for its capability only if all
six of the following hold.** Any one failing means it stays
`enabled_by_default: false` — a strong non-default entry beats a weak
default, per this brief's rule 13 ("if unsure, degrade safely instead of
failing silently").

## The 6 criteria

### 1. Latency: meets `expected_latency_ms`, degrades within `max_latency_ms`

The candidate must have been **actually benchmarked** (via
`scripts/ai_models/benchmark_all_models.py` for model inference, or
`scripts/edge_ai/benchmark_edge_ai_stack.py` for routing/orchestration
latency) with a real `pass` result at or below the registry entry's own
declared `expected_latency_ms` — on the entry's declared `target_board`,
not a substitute machine, once real hardware is available. If it cannot
beat `expected_latency_ms` but can still return within `max_latency_ms`
before `resource_guard`/`inference_scheduler`'s timeout fires, it may
qualify as the default **with `fallback_active` visible on the dashboard**,
never silently.

*Why:* rule 12 ("every long-running inference must have timeout, bounded
queue, and resource guard") is meaningless if a default model is chosen
without ever having been timed.

### 2. Resource budget: fits `expected_ram_mb` / `expected_storage_mb` for its `target_board`

Verified against the real board's known constraints
(`config/pi_efficiency_profile.yaml`, `config/models/pi_ai_hat_plus_2_profile.yaml`)
— a Pi-2 default must not, combined with every other `enabled_by_default`
entry sharing that Pi, exceed the Pi's real RAM. This is a **combined**
budget check across all simultaneously-loaded defaults, not a per-model
check in isolation.

*Why:* "small model + smart routing" (this brief's core principle) fails
if "small" is only true for one model in isolation and the Pi still swaps
under the combined real load.

### 3. Fallback: has a real, working `fallback_model_id`

The declared fallback must itself be a real, registered entry (verified by
`ModelRegistry.validate()` and `ModelRuntimeSelector`'s fallback-chain
resolution) that a caller genuinely receives when the default is
unavailable — not a `null` or a chain that terminates in an exception.

*Why:* rule 11, verbatim: "every AI model must have a fallback path." A
model with no working fallback cannot be a *default* — it can only be an
optional, explicitly-opted-into choice.

### 4. Safety separation: zero `UNSAFE_DIRECT_CONTROL` findings on its real output path

Every action category the candidate's real output can produce (as
classified by `SafetySeparationGuard.classify()`) must resolve to
`TEXT_ONLY`, `INFO_LOOKUP`, `STAFF_ALERT`, `NAVIGATION_REQUEST`, or
`ACTUATION_REQUEST` — never `UNSAFE_DIRECT_CONTROL`. For any capability
whose output could plausibly reach navigation or actuation
(`intent_classification`, `human_state_fusion`-derived behavior proposals),
this must be demonstrated with a real classify() call in a test, not
asserted by inspection alone (see
[`tests/edge_ai/test_safety_separation_guard.py`](../tests/edge_ai/test_safety_separation_guard.py)'s
`TestNeverAllowTable`).

*Why:* rules 1–6 collectively forbid any AI-Pi/LLM/UI output from becoming
a direct hardware command. A default choice is exactly the kind of "quiet"
decision that must not be allowed to silently reintroduce GAP-E1's mistake.

### 5. License: clears `LicenseChecker` with no manual override required

`LicenseChecker.check(entry, explicit_approval=False)` must return
`allowed=True` unconditionally — a candidate that only downloads/runs with
`explicit_approval=True` (a human override) can be *registered* and used
opt-in, but cannot be the unattended default a fresh deployment picks up
automatically.

*Why:* an automatic default is, by definition, unattended — it must never
require a human in the loop just to become active.

### 6. Health: real, non-fabricated benchmark result — never `blocked`

The candidate's most recent `scripts/*/benchmark_*.py` run must report
`pass` (or `fail` with a real, fixable reason already being tracked as a
gap), never `blocked`. `blocked` means the candidate was never actually
exercised on this environment — a model that has never run cannot be
trusted as the thing every fresh deployment silently depends on.

*Why:* matches this pass's consistent "no fake PASS" principle (rule 8)
extended to defaults specifically — a default is a claim about what will
run in production, and that claim must be backed by at least one real run.

## How this applies today (a snapshot, not a re-audit)

| Capability | Current default | Criteria 1–6 status |
|---|---|---|
| `local_llm` | `llm_qwen25_05b` | 1 ✅ (real Pi-2 benchmark, see `docs/PI2_QWEN25_05B_SETUP_REPORT.md`), 2 ✅, 3 — no fallback declared (flagged, see `docs/AI_MODEL_GAP_ANALYSIS.md`), 4 ✅, 5 ✅, 6 ✅ on real hardware / `blocked` on this dev sandbox (no Ollama here) |
| `tts` | `tts_piper_en` | 1 ⚠️ (5.3–5.8s cold-start on dev sandbox, not yet Pi-measured), 2 ✅, 3 ✅, 4 ✅, 5 ✅, 6 ✅ (`pass` in `docs/AI_MODEL_BENCHMARK_REPORT.md` Run 2) |
| `object_detection` / `person_detection` | none | criterion 6 unmet — never benchmarked (`blocked`, no `enabled_by_default` entry exists at all per GAP-2) — correctly has **no default** rather than a guessed one |
| `human_state_fusion` | `human_state_fusion_bonbon` | 1 ✅ (real code, no ML latency), 2 ✅, 3 ✅ (`human_state_fusion_degraded`), 4 ✅ (`tests/edge_ai/test_safety_separation_guard.py`), 5 ✅ (N/A license), 6 ⚠️ — this pass's `is_available()` check reports it unavailable in this sandbox (no bespoke checker for `pi_cpu`/`unavailable` combination yet, see `tests/edge_ai/test_runtime_selector.py`) — needs a bespoke availability checker before it can claim criterion 6 on real hardware |

This table is illustrative, not exhaustive — it exists to show the gate
being applied honestly (including entries that fail it), not to claim
every capability has been re-audited against all six criteria in this
pass.
