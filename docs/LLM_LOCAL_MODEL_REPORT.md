# Local LLM Model Report

Phase 3/14 (selection) + Phase 9 (safety separation). Covers the local
LLM: model selection, why it's small, and — most importantly — the
mechanism that keeps rule 5 ("do not let the LLM directly control
navigation, motors, servos, or safety") true structurally, not just by
convention.

## Selected model: **Qwen2.5 0.5B** (`llm_qwen25_05b`)

- License: Apache-2.0, no acceptable-use conditions (unlike Llama 3.2's
  Community License, which is registered as `llm_llama32_1b` for
  benchmark comparison only, not default).
- Runtime: `ollama_http` — same interface already deployed and verified
  on real Pi-2 hardware.
- **Already pulled and benchmarked on the real Pi-2** on 2026-07-06 — see
  `docs/PI2_QWEN25_05B_SETUP_REPORT.md`. That result is authoritative and
  is not re-claimed in this pass's (Windows sandbox, no Ollama) benchmark
  run (`docs/AI_MODEL_BENCHMARK_REPORT.md`), which honestly reports the 4
  LLM cases as `blocked` on this machine.
- `llm_qwen25_15b` is registered as a larger candidate for future
  benchmark comparison, `enabled_by_default: false` — requires explicit
  human approval to even download (`tests/ai_models/test_license_guard.py`
  enforces this).

## Rule 5 enforcement — structural, not conventional

Three independent layers, all pre-existing in `bonbon_llm` and verified
(not built) this pass:

1. **`SafetyCommandFilter`** (`bonbon_llm/safety/command_filter.py`) —
   every piece of LLM output text is scanned against ~25 hard-blocked
   regex patterns (`cmd_vel`, `Twist`, `navigate_to_pose`, `GPIO`, `PWM`,
   `servo.*angle`, `os.system`, `eval(`, `disable.*safety`, etc.) before
   anything is dispatched. A behavior *class* proposal (e.g.
   `navigate_to`) is never auto-SAFE — it's RISKY, requiring Safety
   Supervisor authorization.
2. **`Pi2LLMGuard`** (`bonbon_llm/core/pi2_llm_guard.py`) — hard resource
   ceiling (max 1 concurrent request, max 64 output tokens, 1.0s
   first-token budget) and load-based disable (high CPU/temp/unsafe
   safety state) specific to the Pi-2 Qwen deployment.
3. **`ModelEntry` schema itself has no actuation-authority field** — there
   is no `can_control_motors`-shaped flag anywhere in the registry schema
   to even misconfigure. Confirmed structurally in
   `tests/llm_local/test_qwen_safety.py::test_registry_grants_the_llm_no_actuation_authority_fields`.

All three verified together in `tests/llm_local/test_qwen_safety.py` (11
tests, all pass) — including the specific case of an LLM output that
looks like it's trying to call `navigate_to_pose` or disable the e-stop,
confirmed BLOCKED.

## Resolution order (existing, unchanged): rule-engine → RAG → LLM

The LLM is the **last resort**, not the first responder — deterministic
rule matching and RAG retrieval are tried first (see
`docs/AI_MODEL_GAP_ANALYSIS.md`'s local-RAG section and
`bonbon_llm/core/rag_retriever.py`). Tasks that must never reach the LLM
at all (never even attempted, not just filtered after the fact):
navigation waypoint computation, motor/servo commands, safety-state
transitions, token/queue number arithmetic, room/department lookup
(deterministic — `faq_hospital_deterministic` in the registry), and PIN/
auth validation. These stay in existing deterministic code paths
(`bonbon_customer_ui` backend, `bonbon_safety`, `bonbon_actuation`) that
predate and are untouched by this AI-model pass.

## Verdict: **PASS** (safety layer) / **PARTIAL** (fresh benchmark) — the model and its safety envelope are correctly selected, wired, and tested; the one real-hardware benchmark data point that exists (Pi-2, 2026-07-06) is treated as authoritative and not re-claimed here.
