# Edge Model Export Report

## Export format policy (`config/data/model_export_targets.yaml`)

| Capability | Format | Fallback | Hardware |
|---|---|---|---|
| object_detection, person_detection | hailo_hef | onnx | hailo_8 |
| gesture_recognition | tflite | onnx | pi_cpu |
| face_emotion, voice_emotion | onnx | — | pi_cpu |
| asr | onnx | — | pi_cpu |
| tts | wav_cache | onnx | pi_cpu |
| local_llm | gguf | — | pi_cpu |
| hospital_knowledge_rag | sqlite_vector | — | pi_cpu |
| navigation | onnx | — | pi_cpu (parameter tuning only, not a real exported model) |

`local_llm` never targets `hailo_hef` — matches rule 6 (LLM must not control motors/servos/Nav2/safety) at the export layer too: an LLM artifact is never treated as a vision-accelerator deployment. Verified: `tests/data_pipeline/test_edge_export_policy.py::test_local_llm_selects_gguf_never_hailo`.

## Export scripts

- `scripts/data/export_object_model_to_hailo.sh` — real `hailomz compile` invocation; **HARDWARE_BLOCKED in this environment** (no Hailo Dataflow Compiler installed), same honesty discipline as `scripts/ai_models/install_hailo_models.sh` — checks for the toolchain and reports exactly what's missing rather than fabricating a compile result.
- `scripts/data/export_gesture_model_onnx.sh` — real, functional `torch.onnx.export` wrapper; runs when PyTorch is available, no special hardware needed.
- `scripts/data/build_asr_phrase_dictionary.py` / `build_tts_phrase_cache.py` — real, functional; honestly report zero output when no hospital phrase list exists yet (current repo state).
- `scripts/data/update_rag_index.py` — real, functional SQLite + JSONL index builder; honestly reports zero documents indexed when no hospital document source exists yet (current repo state). **Not yet wired** into `bonbon_llm.core.rag_retriever.RAGRetriever` (which has no file-based load hook today, only in-code seeding) — stated as a follow-up integration task, not claimed done.

## Edge deployment status tracking

`bonbon_data_pipeline.export_for_edge.EdgeDeploymentTracker` — JSON-file-backed record of the currently ACTIVE vs. FALLBACK model per capability, the real data source behind `GET /data/edge-models`.

- **Promotion auto-creates a rollback path:** `set_active()` with no explicit fallback automatically demotes the previous active model to fallback — verified `test_edge_export_policy.py::test_second_promotion_automatically_gets_previous_as_fallback`.
- **Rollback never silently no-ops:** a capability with no recorded fallback raises `RollbackUnavailableError` rather than doing nothing — verified `test_rollback_without_any_fallback_raises_rather_than_silently_noop`.
- **Rollback is itself reversible:** rolling back records the rolled-back-FROM model as the new fallback — verified `test_rollback_restores_the_previous_model_as_active`.

## Current honest state

Zero edge deployments are recorded today (`EdgeDeploymentTracker.all()` returns empty on a fresh install) — nothing has gone through this pass's export/promotion flow yet on real hardware. `GET /data/edge-models` reports this honestly (`count: 0`), not a fabricated "deployed" status.
