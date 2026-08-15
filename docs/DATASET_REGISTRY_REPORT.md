# Dataset Registry Report

**Scope:** `bonbon_data_pipeline.dataset_registry` + `config/data/dataset_registry.yaml` — the source-training-data registry this pipeline adds. Distinct from `bonbon_ai_model_registry` (deployed model artifacts) and `config/dataset_license_checklist.yaml` (per-capability rollup status, kept and still accurate at that coarser grain).

## What's registered

28 datasets across the 8 brief categories (`config/data/dataset_registry.yaml`), every entry carrying all 15 required fields (`dataset_id`, `name`, `source_url`, `capability`, `domain`, `license`, `commercial_allowed`, `privacy_risk`, `download_allowed`, `intended_use`, `prohibited_use`, `preprocessing_needed`, `target_model`, `evaluation_metric`, `edge_export_format`, `status`).

| Category | Datasets | Notes |
|---|---|---|
| ASR (en/hi/te) | 6 | Common Voice ×3 languages, Sarvam ASR (official API only), consented mic recordings, hospital phrase list |
| TTS | 1 | Sarvam Bulbul (official API only) — Piper/sherpa-onnx voices are deployed MODELS, tracked in `bonbon_ai_model_registry`, not here |
| Object detection | 5 | Hailo Model Zoo, COCO 2017, Open Images V7, BonBon hospital images, synthetic renders |
| Gesture | 4 | MediaPipe landmark extraction, 20BN-Jester (BLOCKED, NC license), BonBon camera samples, synthetic variations |
| Face recognition | 1 | Consent-based staff enrollment only — no public-scrape dataset is or will be registered |
| Emotion | 3 | RAVDESS (BLOCKED, NC license), FER-2013 (unknown license), BonBon field signals |
| Navigation | 4 | LiDAR maps, Nav2 logs, simulated maps, blocked-path failure logs |
| RAG/knowledge | 4 | Hospital documents, directory data, semantic map labels, FAQ table |

## Status distribution (honest, as of this pass)

- **APPROVED: 6** — every one is either fully synthetic/internally-generated (no external rights question) or an already-anonymized internal event log. `registry.validate()` returns zero problems.
- **NEEDS_REVIEW: 20** — the honest majority. A well-documented public license (e.g. Common Voice's CC0) does **not** by itself mean this repo's maintainers reviewed and accepted the dataset — that human step hasn't happened yet for any external corpus.
- **BLOCKED: 2** — `public_gesture_dataset_jester` (CC BY-NC-SA 4.0) and `ravdess_voice_emotion` (CC BY-NC-SA 4.0), both real, non-hypothetical examples of rule 2 (commercial-disallowed blocks production training) firing correctly, verified live in `tests/data_pipeline/test_license_checker.py`.

## What this replaces vs. extends

- Does **not** replace `config/dataset_license_checklist.yaml` — that file's per-capability grain (`NOT_SOURCED`/`CLEARED`) is still the right level for a fast dashboard glance; this registry is the per-dataset detail underneath it.
- Does **not** duplicate `bonbon_ai_model_registry.ModelRegistry` — verified no overlapping `dataset_id`/`model_id` namespace, and the two answer different questions (raw data vs. deployed artifact).
