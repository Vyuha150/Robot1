# Edge AI Model Strategy Report

Phase 15 summary of Phase 3's deliverable: populating
[`config/edge_ai/model_registry.yaml`](../config/edge_ai/model_registry.yaml)
with the 3 capabilities the earlier AI-model-stack pass's 16-capability,
39-entry registry never covered — `human_state_fusion`,
`intent_classification`, `assistant_guardrails` — merged with the
existing registry via `bonbon_edge_ai_runtime.model_registry.load_merged()`
into one 45-entry, 19-capability `ModelRegistry`, never a second
competing one.

## Why these 3, and why none of them is an ML model

All three are **deliberately rule/fusion-based, not model-based, by
design**:

- **`human_state_fusion`** — pure fusion logic over other modules'
  already-model-backed outputs (person tracks, face/voice emotion,
  gesture, speaker turn, intent) into one `HumanState` per person. There
  is nothing for a model to infer here; the inputs are already inferred.
- **`intent_classification`** — a keyword/rule-based classifier that runs
  **upstream** of `task_router.py`'s rule → cache → RAG → LLM decision.
  Using an LLM to classify intent before deciding whether to call the LLM
  would be circular and defeats the entire cost-routing purpose of this
  brief's core principle.
- **`assistant_guardrails`** — `SafetyCommandFilter` + `HallucinationGuard`
  + `CommandAuthorizer`, all regex/rule-based. An LLM must never be the
  thing deciding whether its own output is safe — that would defeat the
  guardrail's entire purpose.

Each has a real primary entry (already-present application code, e.g.
`bonbon_human_state_fusion`, `bonbon_llm/safety/*`) and a real terminal
fallback entry (`*_degraded`/`*_unknown`/`*_deny_all`) — satisfying rule
11 ("every AI model must have a fallback path") even though "model" here
means deterministic code, not weights.

## Registry entries (16 required fields each, all populated)

Each of the 6 new entries carries `model_id`, `capability`, `model_name`,
`provider`, `runtime`, `hardware_target`, `expected_latency_ms`,
`expected_ram_mb`, `expected_storage_mb`, `fallback_model_id`,
`enabled_by_default`, `dashboard_visible`, `download_type`,
`download_command`, `license`, `commercial_allowed` — matching the same
`ModelEntry` schema the base registry's 39 entries already use (no
second, incompatible schema).

## Verification

- `tests/edge_ai/test_model_registry.py`: merge is additive (≥45 entries,
  0 validation problems from `ModelRegistry.validate()`), all 3 new
  capabilities present with exactly one default and a working fallback
  each, and the original 16 capabilities' 39 entries are untouched by the
  merge.
- `tests/edge_ai/test_runtime_selector.py` documents a real, honest gap:
  on any machine without a bespoke availability checker for the
  `hardware_target="pi_cpu"` + `download_type="unavailable"` combination,
  `ModelRuntimeSelector.is_available()` fails closed (no generic checker
  exists for that combination — see rule 1, "never fake availability"),
  so all 3 new capabilities' *primary* entries currently report
  unavailable and the selector honestly falls back to their terminal
  mock/degraded/deny-all entries. **This is flagged, not silently
  accepted** — see [`EDGE_AI_DEFAULT_MODEL_CRITERIA.md`](EDGE_AI_DEFAULT_MODEL_CRITERIA.md)'s
  `human_state_fusion` row and criterion 6: a bespoke checker (verifying
  the real application code is importable/running) is needed before
  these 3 capabilities can honestly claim to resolve to their primary
  entry rather than their fallback on real hardware.
