# Online Dataset Strategy

Rule of thumb that governs every row below: **public datasets buy base
capability; BonBon's own environment buys final performance; BonBon's own
failure cases buy the fastest improvement per labeling-hour.** No category
skips the third step — a model that is only ever evaluated on public
benchmarks has never been checked against this robot's cameras, this
microphone array, this corridor width, or this accent mix.

For how a labeled failure becomes a permanent regression check, see
[FIELD_LEARNING_LOOP.md](FIELD_LEARNING_LOOP.md). For the licensing gate
every dataset goes through before use, see
[DATASET_LICENSE_CHECKLIST.md](DATASET_LICENSE_CHECKLIST.md). For how a
dataset turns into a deployed model, see
[MODEL_TRAINING_AND_FINE_TUNING_PLAN.md](MODEL_TRAINING_AND_FINE_TUNING_PLAN.md).
For what may never be collected without consent, see
[PRIVACY_SAFE_DATA_COLLECTION.md](PRIVACY_SAFE_DATA_COLLECTION.md).

## 1. Object detection

- **Possible public dataset types:** general object-detection benchmarks (COCO-class, Open Images-class licensing families), indoor-scene-specific detection sets.
- **What it improves:** baseline recall on common object classes, robustness to scale/occlusion/lighting variety far beyond what one site can capture.
- **What it cannot solve:** BonBon-specific objects (the robot's own charging dock, site-specific signage, this building's furniture), Hailo-quantization-induced accuracy loss, or this camera's specific lens distortion.
- **License check required:** yes, every time — see checklist. Some popular sets are research-only and block commercial deployment.
- **Privacy risk:** low for objects, but person-containing frames in public sets carry the same face-privacy obligations as a self-collected dataset.
- **Model training use:** pretraining the detector backbone.
- **Validation use:** sanity-checking precision/recall before any site-specific tuning.
- **Fine-tuning use:** light fine-tuning toward the deployed class list.
- **BonBon-specific data still required:** yes — site-specific object classes and Hailo-quantized accuracy must be validated on BonBon's own captured frames (family 7, `tests/production/test_object_recognition_scenarios.py`).

## 2. Person detection

- **Possible public dataset types:** pedestrian/person-detection benchmarks, indoor human-presence sets.
- **What it improves:** baseline person localization across body poses, clothing, and crowd density.
- **What it cannot solve:** this robot's camera height/FOV, the specific occlusion patterns of its deployment sites, or its own re-identification embedding quality.
- **License check required:** yes — person-detection sets are exactly the category most likely to carry restrictive face/biometric clauses even when the bounding boxes themselves are object-level, not identity-level.
- **Privacy risk:** medium — even anonymized person boxes can be re-identifiable in small public datasets; treat as personal data by default.
- **Model training use:** pretraining the detector.
- **Validation use:** baseline recall check.
- **Fine-tuning use:** density/occlusion robustness fine-tuning.
- **BonBon-specific data still required:** yes — family 8 (multi-person tracking) ID-switch rate is only meaningful measured on BonBon's own multi-person sequences.

## 3. Pose / gesture recognition

- **Possible public dataset types:** human pose estimation benchmarks, hand-gesture recognition sets.
- **What it improves:** baseline keypoint/gesture classifier accuracy across body types and viewing angles.
- **What it cannot solve:** BonBon's specific gesture vocabulary (`stop_palm`, `come_here`, `go_away` — these are product-defined, not in any public taxonomy), or this camera's frame rate / resolution trade-offs.
- **License check required:** yes.
- **Privacy risk:** medium (body pose is biometric-adjacent in several jurisdictions).
- **Model training use:** pretraining the pose backbone.
- **Validation use:** baseline keypoint accuracy.
- **Fine-tuning use:** transfer to BonBon's specific gesture vocabulary.
- **BonBon-specific data still required:** yes, heavily — the entire `stop_palm`/`conflicting_gestures` safety-relevant vocabulary (family 9) has no public-dataset equivalent and must be collected and labeled directly.

## 4. Speech recognition (ASR)

- **Possible public dataset types:** multilingual speech corpora covering the languages in `telugu_hindi_english` (family 10), accented-speech sets, noisy-speech augmentation sets.
- **What it improves:** baseline word-error-rate across languages/accents far beyond what a single deployment site could collect.
- **What it cannot solve:** this microphone array's specific frequency response, this robot's own fan/motor noise profile, or the exact emergency-phrase vocabulary the safety system listens for.
- **License check required:** yes — several corpora are research-only or require attribution incompatible with a closed product.
- **Privacy risk:** high — speech is biometric and content-bearing; public corpora that include real human speakers carry consent obligations the publisher is responsible for, but redistribution/derivative-model terms still apply to BonBon.
- **Model training use:** pretraining/base ASR model.
- **Validation use:** WER baseline across the documented language/accent matrix.
- **Fine-tuning use:** domain adaptation to robot-relevant vocabulary and the deployment site's ambient noise profile.
- **BonBon-specific data still required:** yes — the `emergency_phrase` recognition path (family 10) is safety-critical and must be validated on this robot's own mic array, not just a public WER number.

## 5. Speaker diarization

- **Possible public dataset types:** multi-speaker conversational corpora with diarization labels.
- **What it improves:** baseline speaker-change-detection and clustering accuracy.
- **What it cannot solve:** this robot's specific mic array geometry (which drives directional/beamforming cues), or its real-world speaker count distribution (`one_person` through `crowd`).
- **License check required:** yes.
- **Privacy risk:** high (same as ASR — diarization output can itself be a biometric identifier).
- **Model training use:** pretraining the diarization model.
- **Validation use:** diarization-error-rate baseline.
- **Fine-tuning use:** adapting to the deployed mic array's directional characteristics.
- **BonBon-specific data still required:** yes — `active speaker assignment accuracy` (family 10 metric) only means something measured on this hardware.

## 6. Voice emotion

- **Possible public dataset types:** emotional speech corpora (acted or naturalistic).
- **What it improves:** baseline tone/affect classification.
- **What it cannot solve:** reliable ground truth for real-world ambiguous affect — even state-of-the-art voice-emotion models are noisy, and acted-emotion corpora over-represent exaggerated affect vs. real users.
- **License check required:** yes.
- **Privacy risk:** high — emotional state is sensitive personal data in several privacy frameworks (e.g. GDPR special-category-adjacent treatment).
- **Model training use:** pretraining only.
- **Validation use:** sanity baseline, not a deployment gate.
- **Fine-tuning use:** rarely justified given the signal's inherent noise; prefer spending the budget on fusion-confidence calibration instead (family 11).
- **BonBon-specific data still required:** yes, and more importantly: **per the [SCENARIO_FAMILIES.md](SCENARIO_FAMILIES.md) family-11 rule, voice emotion output is always treated as an uncertain signal that gates behavior strength, never as ground truth** — no amount of dataset improvement changes that policy.

## 7. Face emotion

- Same profile and same policy as voice emotion (6): public corpora bootstrap a classifier, BonBon data tunes it, and **the output is always an uncertain signal**, never a behavior trigger on its own (`bonbon_behavior_validation.perception_assertions.low_confidence_handled_correctly`). Privacy risk is higher than voice emotion — face imagery is the single most sensitive modality this robot touches; see PRIVACY_SAFE_DATA_COLLECTION.md's explicit no-default-storage rule.

## 8. Navigation / spatial reasoning

- **Possible public dataset types:** indoor navigation benchmark environments (simulation-based), generic SLAM/obstacle datasets.
- **What it improves:** baseline planner robustness across generic obstacle shapes/indoor layouts in simulation.
- **What it cannot solve:** this robot's actual physical footprint, sensor placement, wheel dynamics, or the actual floor plans of its deployment sites — none of these transfer from a public dataset.
- **License check required:** yes (mostly simulation-asset licenses).
- **Privacy risk:** low (rarely contains identifiable people as the primary subject).
- **Model training use:** pretraining a general obstacle-avoidance policy in simulation.
- **Validation use:** sanity-checking the planner in unfamiliar synthetic layouts before site deployment.
- **Fine-tuning use:** minimal — navigation correctness is dominated by site-specific maps, not a fine-tunable perception model.
- **BonBon-specific data still required:** **always, and primarily** — per the brief's own rule, "Navigation must be validated on BonBon's own maps and logs," full stop. Public navigation data is bootstrap-only.

## 9. Behavior validation

- **Possible public dataset types:** none directly applicable — "is this the correct robot behavior for this scenario" is a product-specific judgment, not a labeled public corpus.
- **What it improves:** nothing directly; at most, public HRI research literature informs initial expected-outcome design (`bonbon_behavior_validation/expected_outcomes.py`).
- **What it cannot solve:** anything — there is no substitute for the scenario-family + Behavior Oracle + field-failure-to-regression-test loop this framework implements.
- **License check required:** n/a.
- **Privacy risk:** n/a (no external data ingested).
- **Model training use:** n/a.
- **Validation use:** this *is* the validation layer (`tests/production/`, Phase 3's `BehaviorOracle`).
- **Fine-tuning use:** n/a.
- **BonBon-specific data still required:** **100% — this category is BonBon-specific by definition.**

## Rules (restated, operative)

1. Use public datasets for base capability. Never skip straight to fine-tuning a from-scratch model on a handful of field examples.
2. Use BonBon environment data for final performance. A model that has only seen public data has not seen this robot's hardware.
3. Use failure-case data for the fastest improvement — a single well-labeled field failure that becomes a regression scenario (Phase 6) is worth more than a large batch of generic public examples, because it directly targets the gap the robot actually has.
4. Do not train directly on unlicensed copyrighted/private data. Every dataset goes through DATASET_LICENSE_CHECKLIST.md before it touches a training run.
5. Do not store raw face/audio without explicit consent/debug mode — enforced structurally by `bonbon_field_learning.anonymized_event_store` (no raw-media fields exist on the type) and the separate, explicit-only `DebugSnapshotStore`.
6. Emotion models (voice and face) are always treated as uncertain signals, encoded directly in the Behavior Oracle's `low_confidence_handling` check and family 11's policy — not a data quality problem to be solved away.
7. Navigation is validated on BonBon's own maps and logs — public navigation data never substitutes for this (family 6, family 9 in production tests).
