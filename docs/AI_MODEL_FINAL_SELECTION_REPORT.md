# AI Model Final Selection Report

Phase 12 of the AI model upgrade brief. This is the authoritative summary
of every model registered in `config/models/model_registry.yaml` (39
entries across 16 capabilities), which one is selected as default per
capability, why, and what it falls back to. Source of truth for this
table is the registry file itself plus
`bonbon_ai_model_registry.model_registry.ModelRegistry` — this document
is generated from and must stay consistent with that data, not the other
way around.

Legend: **★** = `enabled_by_default: true` (what actually runs today
absent a hardware profile override). `hw` = `hardware_target`.
`commercial_ok` = `unknown` means the license text does not plainly say
either way and must be manually verified before commercial deployment
(never auto-resolved to "yes").

## Local LLM

| | model_id | runtime | hw | license | commercial_ok | fallback |
|---|---|---|---|---|---|---|
| ★ | `llm_qwen25_05b` | ollama_http | pi_cpu | Apache-2.0 | true | — (terminal) |
| | `llm_qwen25_15b` | ollama_http | pi_cpu | Apache-2.0 | true | — (benchmark-only, larger) |
| | `llm_llama32_1b` | ollama_http | pi_cpu | Llama 3.2 Community License (Meta) | true (conditions apply) | — (benchmark-only) |

**Selected: Qwen2.5 0.5B.** Smallest real-time-viable model for Pi 5 CPU
inference, permissively licensed (Apache-2.0, no acceptable-use
conditions unlike Llama 3.2), and already verified running on real Pi-2
hardware (`docs/PI2_QWEN25_05B_SETUP_REPORT.md`, 2026-07-06). The 1.5B
variant is registered for benchmark comparison only, not enabled by
default — larger model, no confirmed Pi-5-real-time benchmark yet.
**Never given navigation/motor/safety authority** — enforced by
`bonbon_local_rag`'s deterministic-task separation (rule 5/9), not by
this registry alone.

## ASR (speech-to-text)

| | model_id | runtime | hw | license | commercial_ok | fallback |
|---|---|---|---|---|---|---|
| | `asr_sarvam_edge` | sarvam_edge_or_api | external_api | Commercial (Sarvam) | unknown | → asr_faster_whisper |
| ★ | `asr_faster_whisper` | ctranslate2 | pi_cpu | MIT (wrapper) + MIT (Whisper weights) | true | → asr_sherpa_onnx |
| | `asr_sherpa_onnx` | onnxruntime | pi_cpu | Apache-2.0 | true | → asr_whisper_cpp |
| | `asr_whisper_cpp` | ggml | pi_cpu | MIT + MIT | true | → asr_degraded_template |
| | `asr_degraded_template` | none | mock (terminal) | N/A | true | none |

**Chain: Sarvam Edge → faster-whisper → sherpa-onnx → whisper.cpp →
degraded template.** Sarvam sits first per rule 12 (preferred Indian-
language engine *only if* official Edge/API access exists — verified live
per-call by `bonbon_sarvam_adapter`, never assumed). `asr_faster_whisper`
is the open-source default because it's the best accuracy/speed balance
for Pi 5 CPU among openly-licensed engines. The terminal
`asr_degraded_template` guarantees the pipeline always returns *something*
(an empty/templated transcript) rather than crashing when every real
engine is unavailable — this is what `speech_ai.asr_router`'s bug fix
this session made actually reachable (see
`docs/SPEECH_AI_UPGRADE_REPORT.md`).

## TTS (text-to-speech)

| | model_id | runtime | hw | license | commercial_ok | fallback |
|---|---|---|---|---|---|---|
| | `tts_sarvam_edge` | sarvam_edge_or_api | external_api | Commercial (Sarvam) | unknown | → tts_piper_en |
| ★ | `tts_piper_en` | piper_subprocess_or_api | pi_cpu | MIT + CC0/MIT voice | true | → tts_sherpa_onnx |
| | `tts_piper_hi` | piper_subprocess_or_api | pi_cpu | Piper voice license (verify per voice) | true | → tts_cached_phrase |
| | `tts_sherpa_onnx` | onnxruntime | pi_cpu | Apache-2.0 | true | → tts_cached_phrase |
| | `tts_cached_phrase` | audio_playback | mock | N/A (recorded asset) | true | → tts_text_only |
| | `tts_text_only` | none | mock (terminal) | N/A | true | none |

**Chain: Sarvam Edge → Piper (EN) → sherpa-onnx → cached phrase →
text-only.** Piper is the open-source default — MIT-licensed, small,
fast, purpose-built for embedded CPU TTS. `tts_piper_hi` is registered
separately (Hindi voice) since Piper voices are per-language assets, not
a single multilingual model; **no Telugu Piper voice is registered** —
see the ASR/TTS status caveat below. `tts_cached_phrase` /
`tts_text_only` are the honest terminal fallbacks (pre-recorded phrase
audio, then text-only display) so the pipeline degrades instead of going
silent-and-broken.

**Known gap, not silently hidden:** no Telugu TTS entry exists yet
(GAP-8 in `docs/AI_MODEL_GAP_ANALYSIS.md`) — Telugu falls through to
Sarvam (if access exists) or the English/cached fallback otherwise. This
is registered honestly as a gap, not papered over with a fake entry.

## Wake word / VAD

| | model_id | runtime | hw | license | commercial_ok | fallback |
|---|---|---|---|---|---|---|
| ★ | `wake_openwakeword` | onnxruntime | pi_cpu | Apache-2.0 | true | none |
| | `wake_porcupine` | picovoice_sdk | external_api | Commercial (Picovoice) | unknown | → wake_openwakeword |
| ★ | `vad_silero` | torch | pi_cpu | MIT | true | none |

**openWakeWord + Silero VAD**, both fully open-source, no gated access,
no cloud dependency — the correct default per rule 4 (no cloud API by
default). Porcupine registered as a documented alternative only (free
tier has usage limits — not unconditionally open, so it is not the
default).

## Translation

| | model_id | runtime | hw | license | fallback |
|---|---|---|---|---|
| ★ | `translation_none` | none | mock (terminal) | N/A | none |
| | `translation_sarvam` | sarvam_edge_or_api | external_api | Commercial | → translation_none |

No open-source translation model is registered as a real backend —
translation is Sarvam-or-nothing today, honestly reflected by
`translation_none` (pass-through / untranslated) being the default until
Sarvam access is confirmed.

## Object / person detection

| | model_id | runtime | hw | license | commercial_ok | fallback |
|---|---|---|---|---|---|---|
| | `vision_hailo_yolo` | hailort | hailo_8 | Hailo Model Zoo (mixed, verify per model) | unknown | → vision_cpu_onnx_runtime_adapter |
| | `vision_cpu_onnx_runtime_adapter` | onnxruntime | pi_cpu | depends on loaded `.onnx` | unknown | → vision_ultralytics_direct |
| | `vision_ultralytics_direct` | ultralytics_direct | pi_cpu | AGPL-3.0 (or paid Enterprise) | unknown | → vision_mock |
| | `vision_mock` | none | mock (terminal) | N/A | true | none |
| | `vision_person_hailo_yolo` | hailort | hailo_8 | Hailo Model Zoo (verify) | unknown | → vision_mock |

**No entry is `enabled_by_default`.** This is deliberate per GAP-2:
three real, independent object-detection implementations already exist
in the codebase (`bonbon_vision.YoloDetector`,
`ObjectDetectorRuntimeAdapter`, a raw Ultralytics path) and were
registered honestly rather than arbitrarily crowning one "the" default
without the consolidation work GAP-2 calls for. Until that consolidation
lands, `object_detection`/`person_detection` correctly report
`blocked`/no-active-model on the dashboard rather than a guessed answer —
confirmed in this phase's benchmark run.

## Gesture recognition / pose estimation

| | model_id | runtime | hw | license | fallback |
|---|---|---|---|---|---|
| ★ | `gesture_mediapipe_holistic` | mediapipe | pi_cpu | Apache-2.0 | → gesture_mock |
| | `gesture_mock` | none | mock (terminal) | N/A | none |
| | `gesture_hailo_pose` | hailort | hailo_8 | Hailo Model Zoo (verify) | → gesture_mediapipe_holistic |

**MediaPipe Holistic** is the default — open-source, CPU-viable, and the
one gesture/pose signal path this repo already relies on for
safety-relevant gestures (e.g. `stop_palm`). Per rule 6, gesture
recognition is never routed through the LLM — this is a dedicated
CV model, full stop. Hailo pose is registered as an acceleration path
for when the AI HAT+2 is confirmed present, not yet the default (no
Hailo hardware confirmed active on any real Pi in this deployment as of
this pass).

## Face recognition

| | model_id | runtime | hw | license | commercial_ok | fallback |
|---|---|---|---|---|---|---|
| ★ | `face_mock` | none | mock | N/A | true | none |
| | `face_insightface` | onnxruntime | pi_cpu | code open; **pretrained weights non-commercial research license** | false | → face_deepface |
| | `face_deepface` | tensorflow_keras | pi_cpu | MIT (wrapper) + MIT/BSD weights | true | → face_mock |

**Default is `face_mock`, deliberately.** InsightFace's pretrained
weights are explicitly non-commercial per InsightFace's own model zoo
terms — registering it with `commercial_ok=false` and *not* defaulting
to it is the direct enforcement of rule 3 ("do not download
commercial/gated models without official access"). DeepFace (MIT +
permissive weights) is the real, legally-clear alternative and is
registered as the fallback, but this pass did not flip it to default
without a product decision on enabling always-on face *recognition*
(identity matching) vs. face *emotion* (already defaulted — see below) —
recognition implies persistent identity, a materially different
privacy/consent surface than emotion classification, so it was left
conservative rather than silently escalated.

## Face emotion

| | model_id | runtime | hw | license | fallback |
|---|---|---|---|---|---|
| ★ | `emotion_face_deepface` | tensorflow_keras | pi_cpu | MIT | → emotion_face_mock |
| | `emotion_face_mock` | none | mock (terminal) | N/A | none |

**DeepFace, enabled by default** — this was GAP-1, fixed this session:
DeepFace was already the code's runtime default but was missing from
`requirements/pi2_requirements.txt`, meaning it would have silently
fallen back to mock on a real Pi install. Fixed both the requirements
file and this registry flag together (see
`docs/AFFECTIVE_AI_UPGRADE_REPORT.md`). Per rule 6, this is a dedicated
CV/emotion model — never the LLM.

## Voice emotion

| | model_id | runtime | hw | license | fallback |
|---|---|---|---|---|
| ★ | `voice_emotion_speechbrain` | torch | pi_cpu | Apache-2.0 (SpeechBrain) + MIT (wav2vec2) | → voice_emotion_text_sentiment |
| | `voice_emotion_text_sentiment` | none | mock (terminal) | N/A | none |

Same GAP-1 fix as face emotion — SpeechBrain was the code default,
missing from requirements, now both fixed and registered consistently.

## Speaker diarization

| | model_id | runtime | hw | license | commercial_ok | fallback |
|---|---|---|---|---|---|---|
| ★ | `diarization_active_speaker_approx` | none | mock | N/A | true | none |
| | `diarization_pyannote` | torch | pi_cpu | gated on Hugging Face, restrictive commercial terms without a paid plan | unknown | → diarization_active_speaker_approx |

**Default is the lightweight active-speaker approximation, not
pyannote.** pyannote requires accepting per-model HF terms and a personal
access token, and its commercial-use terms are historically restrictive
without a paid HF plan — registering it as available-but-not-default is
the direct enforcement of rule 3. It is also, per the Phase 10 AI-Pi load
priority, the heaviest model and last to warm up, gated on a real
benchmark + HF token before ever being considered for default.

## Local RAG / hospital FAQ

| | model_id | runtime | hw | license | fallback |
|---|---|---|---|---|
| ★ | `rag_bonbon_llm_chroma` | in_process_python | pi_cpu | app code N/A; chromadb + sentence-transformers both Apache-2.0 | → rag_numpy_fallback |
| | `rag_numpy_fallback` | in_process_python | pi_cpu | N/A | none |
| ★ | `faq_hospital_deterministic` | in_process_python | pi_cpu | N/A | none |

Two separate capabilities intentionally: `local_rag` (semantic retrieval
over hospital docs, LLM-assisted phrasing only) and `hospital_faq`
(deterministic lookup — room numbers, hours, department locations) are
kept apart per rule 9's deterministic-task separation, detailed in
`docs/AI_MODEL_GAP_ANALYSIS.md`'s local-RAG section and
`bonbon_local_rag`'s own docs.

## Summary: what's actually enabled by default today (14 capabilities have one; 2 deliberately don't)

`local_llm`→Qwen2.5 0.5B · `asr`→faster-whisper · `tts`→Piper EN ·
`wake_word`→openWakeWord · `vad`→Silero · `translation`→none (passthrough) ·
`gesture_recognition`→MediaPipe Holistic · `face_recognition`→mock
(licensing-conservative) · `face_emotion`→DeepFace · `voice_emotion`→
SpeechBrain · `speaker_diarization`→active-speaker approximation ·
`local_rag`→Chroma+sentence-transformers · `hospital_faq`→deterministic
lookup · `object_detection`/`person_detection`/`pose_estimation`→**no
default** (GAP-2, awaiting consolidation; Hailo variants exist and are
dashboard-visible but not silently promoted to default without hardware
confirmation).
