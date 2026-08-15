# Training and Fine-Tuning Plan

**Relationship to `docs/MODEL_TRAINING_AND_FINE_TUNING_PLAN.md`:** that doc (existing, from the field-pilot-learning framework) explains the model-evaluation/deployment-gate methodology in prose (`bonbon_field_learning.model_evaluation_tracker.ModelEvaluationTracker.deployment_allowed()`). This doc is the **per-capability dataset → training → export plan** the current brief asks for, backed by a real, checkable config (`config/data/training_targets.yaml`) rather than prose alone — narrower scope, machine-validated.

Rule enforced structurally, not just documented: **no target may name a Raspberry Pi as its `training_machine`.** `bonbon_data_pipeline.training_manifest.TrainingManifest.validate_against_registry()` fails any target whose `training_machine` contains `raspberry_pi`/`pi_1`/`pi_2`/`pi_3`/`hailo`/`edge_board` — verified in `tests/data_pipeline/test_training_manifest.py`.

## Per-capability plan

| Capability | Baseline | Method (Phase 5 recommendation) | Metric | Threshold | Export | Rollback |
|---|---|---|---|---|---|---|
| ASR | faster-whisper (deployed) | Phrase-boost vocabulary first, full fine-tune only if insufficient | word_error_rate | ≤ 0.15 | ONNX | `EdgeDeploymentTracker.rollback('asr')` |
| TTS | Piper en_US-lessac-medium (deployed) | Cached phrases + existing voices first; no new TTS training | mos_naturalness | ≥ 3.5 | wav_cache | `.rollback('tts')` |
| Object detection | yolov8n (Hailo Model Zoo) | Fine-tune on workstation/GPU, ONNX then Hailo HEF | map_50_95 | ≥ 0.55 | hailo_hef | `.rollback('object_detection')` |
| Gesture recognition | landmark-sequence classifier (deployed) | Train from MediaPipe landmarks, not raw video | f1_score | ≥ 0.85 | tflite | `.rollback('gesture_recognition')` |
| Face emotion | DeepFace backend (deployed) | Fusion/rule weighting + uncertainty calibration, not overtraining | uncertainty_calibration_error | ≤ 0.20 | onnx | `.rollback('face_emotion')` |
| Navigation | Nav2 costmap/planner (deployed) | Simulation-first; rule 5 safety verification gates any production change | path_success_rate | ≥ 0.98 | onnx | `.rollback('navigation')` |
| Hospital knowledge RAG | Chroma + SQLite exact-match | Improve structured data first (`update_rag_index.py`) | retrieval_precision_at_k | ≥ 0.90 | sqlite_vector | `.rollback('hospital_knowledge_rag')` |

Every `dataset_ids` entry is cross-checked live against `config/data/dataset_registry.yaml` — `TrainingManifest.validate_against_registry()` run during this pass currently reports **18 blocking issues**, all `NEEDS_REVIEW`/rule-5-unverified, none fabricated as ready. See `GET /api/v1/data/training-runs`'s `blockingIssues` field for the live, current list.

## Workstation/GPU only (rule 7)

Every target's `training_machine` is `workstation_gpu`. The Pi's role is unchanged: inference and telemetry logging only, never training. `scripts/data/export_object_model_to_hailo.sh` and `export_gesture_model_onnx.sh` run on the workstation that did the training and produce the artifact the Pi then only *loads*.
