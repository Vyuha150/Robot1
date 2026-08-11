# AI Model Current Audit

Phase 1 of the AI model stack upgrade. Read-only — no code changed while
producing this document. Every claim below is sourced from the actual
code (file:line), the real Docker-build package manifest
(`requirements/pi2_requirements.txt`), and the only two hardware reports
that exist for this hardware generation (`docs/PI2_QWEN25_05B_SETUP_REPORT.md`,
`docs/PI2_HARDWARE_CHECK_REPORT.md`, both dated 2026-07-06). The Pi
(`wise150@192.168.1.16`) is **not reachable from this dev sandbox this
session** (`ping` timed out) — nothing below claims fresh live
verification unless explicitly marked so.

**Blunt headline finding, load-bearing for the rest of this audit:**
**zero** of the AI/ML packages this stack depends on
(ollama/chromadb/faiss/sentence-transformers/whisper/torch/piper/mediapipe)
are installed in any environment reachable from this session — confirmed
by inspecting the repo's only `.venv` (`bonbon_operator_api`'s dashboard
venv, contains none of them). Every capability below is therefore either
"confirmed working on real Pi-2 hardware on 2026-07-06" (LLM only, the
one thing actually benchmarked) or "real code exists, never verified
running, degrades to mock/None on `ImportError` by design" — the second
category is not a defect (it's the documented lazy-import pattern every
`bonbon_hal` driver also uses), but it means WORKING vs MOCK_ONLY below
reflects **design intent + last confirmed hardware run**, not something
re-verified this pass.

## Capability table

| Capability | Current model | Current runtime | Status | Latency (measured) | CPU/RAM impact (measured) | Dashboard visibility |
|---|---|---|---|---|---|---|
| Local LLM | `qwen2.5:0.5b` (Pi-2 override); **code default is `llama3.2:3b`** | Ollama HTTP API, SDK-or-raw-`urllib` fallback | **WORKING** (real Pi-2 run, 2026-07-06) | avg 3.80s, max 7.53s (7/7 prompts) | 684MB→1.3-1.4GB RSS once loaded; CPU%: instrumentation gap, not measured | PARTIAL — `ConversationData.llm_*` fields exist on `RobotStatus`, no license/runtime/fallback view |
| RAG (bonbon_llm) | ChromaDB→FAISS→NumPy-cosine fallback chain, `sentence-transformers` embeddings→MD5-hash fallback | In-process Python | **MOCK_ONLY** (real code, never run against installed chromadb — not benchmarked on Pi-2 either) | not measured | not measured | NONE |
| RAG (bonbon_data_stores) | ChromaDB, 5 collections | In-process Python | **DEAD CODE** — not imported by `bonbon_llm` or anything else outside `bonbon_data_stores` itself | n/a | n/a | NONE |
| ASR | faster-whisper / openai-whisper selectable; **default backend is `"mock"`** | CTranslate2 (faster-whisper) or PyTorch (whisper) | **MOCK_ONLY by default config**; real backend code exists, unverified on hardware | not measured | not measured | NONE dedicated (transcript text/confidence exists on `ConversationData`, no engine/backend field) |
| VAD | Silero VAD (`torch.hub`) | PyTorch | **PARTIAL** — real backend is the *default* (unlike ASR/wake-word), never hardware-verified | not measured | not measured | NONE |
| Wake word | openWakeWord; **disabled by default**, default backend `"mock"` | ONNX (openwakeword) | **MISSING (disabled)** — Porcupine backend named but "placeholder, not implemented" | not measured | not measured | NONE |
| TTS | Piper, voice `en_US-lessac-medium` (English only) | subprocess or Python API, MockTTS fallback | **WORKING** (per `docs/PI2_HARDWARE_CHECK_REPORT.md` context — Piper itself was verified working on real Pi-2 hardware earlier this session per prior TTS speaker-fix task, English only) | not re-measured this pass | not measured | PARTIAL — `TTSData` (speaking/text/queue) exists, no engine/language/latency field |
| Translation | **none found** | — | **MISSING** | — | — | NONE |
| Object/person detection | `yolo_object_detection.hef`/`person_detection.hef` referenced by path in config; **model files not found in-repo** (expected to be provided at deploy time) | `bonbon_ai_runtime.RuntimeSelector`: hailo→cpu→mock | **BLOCKED** (no Hailo device, no model files confirmed present) — see companion vision-agent findings below | — | — | PARTIAL — `PerceptionData` exists on `RobotStatus`, no per-model runtime/fallback field |
| Hailo runtime | `bonbon_ai_runtime` abstraction, `hailortcli scan` detection | HailoRT (Python bindings) | **BLOCKED** — no Hailo hardware confirmed present as of the 2026-07-06 hardware check (`hailortcli` not even installed then); AI HAT+2 physically undelivered/unconnected at that time | — | — | See `bonbon_ai_runtime`'s own prior dashboard wiring (Phase 6 of an earlier session pass) |
| Object/person detection (duplication) | **3 separate implementations**: `bonbon_vision.YoloDetector` (direct `ultralytics`), `bonbon_vision.ObjectDetectorRuntimeAdapter` (routed through `bonbon_ai_runtime`, opt-in only), `bonbon_perception.YoloPersonDetector` (separate `ultralytics`/`torch.hub`) | ultralytics YOLOv8/v5 direct, or `bonbon_ai_runtime` | **WORKING code / MOCK_ONLY runtime default** — only 1 of 3 detector classes goes through the Hailo/CPU/mock selector, and even that one isn't the default backend | not measured | not measured | PARTIAL |
| Gesture recognition | MediaPipe **Holistic** (pose+both-hands+face-mesh), rules-based classifiers on landmarks | MediaPipe (real default backend, actually instantiated) | **WORKING (code) / hardware-unverified** — 10/16 requested gesture classes genuinely detectable; `come_here` referenced but its detector always returns `False` (placeholder); `go_away` appears only in downstream intent-mapping tables, no detector produces it; `pointing_at_object` and `namaste/folded_hands` don't exist at all | not measured | not measured | NONE dedicated |
| Face detection/recognition | **2 separate implementations**: `bonbon_vision.face_pipeline` (OpenCV-DNN/InsightFace/DeepFace) and `bonbon_perception.face_node` (OpenCV-Haar+LBPH/DeepFace) | Both default to `mock` in bringup | **MOCK_ONLY by default**; real backends exist but unverified; **no enrollment/consent mechanism exists anywhere** — both are read-only lookups against a pre-populated embedding store, contradicting the "consent required for known person database" requirement | — | — | NONE |
| Face emotion | DeepFace (`DeepFace.analyze(actions=["emotion"])`), default backend, per-`tracking_id`, warmed up on activate | `bonbon_affective_ai` | **CODE DEFAULT ACTIVE, but DeepFace is NOT in `pi2_requirements.txt`** — real, previously-undocumented gap (see Gap Analysis GAP-1) | not measured | not measured | Privacy-gated (`privacy_suppressed`/`privacy_level` fields, 3 levels, scores explicitly zeroed when suppressed — well-implemented) |
| Voice emotion | SpeechBrain `emotion-recognition-wav2vec2-IEMOCAP`, default backend, warmed up | `bonbon_affective_ai` (**not** `bonbon_speaker_intelligence` — see below) | **CODE DEFAULT ACTIVE, but SpeechBrain is NOT in `pi2_requirements.txt`** either — same class of gap (GAP-1) | not measured | not measured | NONE dedicated |
| Speaker diarization | pyannote.audio `speaker-diarization-3.1` (gated HF model, needs token) | `bonbon_speech` | **DISABLED by default** (`enabled=False`), correctly gated on a missing HF token rather than silently degrading; also deliberately excluded from `pi2_requirements.txt` (protobuf conflict with mediapipe — documented tradeoff, not an oversight) | — | — | NONE |
| Speaker intelligence (fusion consumer) | N/A — pure consumer | `bonbon_speaker_intelligence` | **WORKING** — explicitly documented as consuming `/speech/transcription`, `/bonbon/affective/voice_emotion`, `/bonbon/persons/tracks` rather than re-running any model (correct architecture, no duplication) | — | — | — |
| Human-state fusion | `HumanStateResult` dataclass (23 fields: track_id, gesture, face/voice emotion, transcript, intent, engagement/urgency/confidence, recommended response style/distance, operator-alert flag, evidence summary) | `bonbon_human_state_fusion` | **WORKING** — genuinely comprehensive, already close to what Phase 8 of this task asks for | — | — | Feeds `ConversationData`/emotion fields on dashboard |
| Multi-person tracking | UUID-based `person_track_id` (`ptrk_...`) + human-friendly `Person_N` counter | `bonbon_multi_person_tracker` | **WORKING** | — | — | — |
| Hailo Model Zoo mapping | `config/runtime/model_runtime.yaml` references generic filenames (`models/hailo/yolo_object_detection.hef`) — **not actual Hailo Model Zoo model identifiers/versions**, and the referenced files don't exist anywhere in the repo (confirmed via exhaustive `find` for `.hef`/`.onnx`/`.pt`/`.engine` — zero results) | `bonbon_ai_runtime.RuntimeSelector` | **CONFIG SCAFFOLDING ONLY** — no real Hailo Model Zoo model has been named, sourced, or downloaded | — | — | — |
| Dashboard model status | `ConversationData`, `TTSData`, `PerformanceData`, `ComponentFaultData` on `bonbon_operator_api`'s `RobotStatus` | FastAPI + WebSocket | **PARTIAL** — real per-capability fields exist for LLM/emotion/TTS/transcript, but no unified model-registry view (license, runtime, fallback-active, benchmark result) anywhere | n/a | n/a | This IS the dashboard |
| Pi resource guard | `Pi2LLMGuard` (LLM only, **disabled by default in code**, enabled via `local_ultra_fast.yaml`); `LoadSheddingController`/`ResourceMonitor`/`BoundedInferenceQueue`/`StaleFrameDropper` (vision/general, Phase 5 of an earlier pass) | In-process | **WORKING** (LLM guard config-enabled on Pi-2; general resource-shedding system unit-tested, hardware-FPS/CPU numbers still BLOCKED per `PI_EFFICIENCY_PROFILE_REPORT.md`) | — | — | PARTIAL |
| Tests | 0 test files under `tests/ai_models/`, `tests/speech_ai/`, `tests/llm_local/`, etc. — **none of these directories exist yet** | — | **MISSING** (this is exactly what Phase 13 of this task creates) | — | — | — |

## Detail: Local LLM

- Ollama-only backend, no cloud path in the automatic pipeline
  (`bonbon_llm/core/ollama_client.py:139-203`) — SDK first
  (`import ollama`), raw HTTP fallback to `{base_url}/api/chat` if the
  SDK isn't installed.
- **Real discrepancy, not yet fixed**: the code-level default model is
  `llama3.2:3b` (`bonbon_llm/config/llm_config.py:25,275`), not
  `qwen2.5:0.5b`. The correct model only takes effect via a Pi-2-specific
  launch-argument override (`bonbon_human_ai_bringup/launch/human_ai_bringup.launch.py:130`,
  `docker-compose.pi2.yml:155`, `config/llm/local_ultra_fast.yaml:30`).
  This was already flagged once before, independently, in
  `docs/THREE_PI_CURRENT_ARCHITECTURE_AUDIT.md:75`. It has not caused an
  incident (the launch/compose override is what actually runs on Pi-2),
  but it means anyone running `bonbon_llm` directly without that specific
  launch path silently gets `llama3.2:3b` instead — a 3B model this
  hardware has never been benchmarked against. **Recommended fix in the
  gap analysis: change the code default itself, not just the override.**
- `bonbon_operator_api`'s manual staff LLM-test tool
  (`api/llm_test_api.py:24,26,51`) also defaults its `model` field to
  `llama3.2:3b` and additionally offers an **opt-in** `openai_compatible`
  provider pointed at `https://api.deepseek.com` by default when that
  provider is explicitly selected. This is **not a rule-4 violation**:
  the tool's own default `provider` value is `"ollama"` (local), the
  cloud path requires an explicit provider switch + a per-request API key
  that is never persisted, it's gated behind `diagnostics:read` auth
  (staff-only), and it's a manual one-shot test endpoint, not part of the
  automatic conversation pipeline. Flagged here for transparency, not as
  a defect.
- `Pi2LLMGuard` (`bonbon_llm/core/pi2_llm_guard.py`) — CPU-disable at
  **85%** (`llm_config.py:213`, not 80% as an earlier session doc
  paraphrased), temp-disable at **75°C**, also disables on safety states
  `{DANGER, FAULT, SAFE_STOP}`. `max_concurrent_requests=1`,
  `max_output_tokens=64`. Guard is **disabled by default in code**
  (`Pi2LLMGuardConfig.enabled=False`) — the Pi-2 deployment profile
  (`local_ultra_fast.yaml:51`) explicitly turns it on. Anyone running
  `bonbon_llm` without that profile gets no CPU/thermal protection at
  all — same class of gap as the model-name default above.
- Real benchmark (2026-07-06, real Pi-2 hardware, standalone script
  against Ollama's HTTP API, no ROS2 dependency): 7/7 prompts completed,
  0 timeouts, 0 heuristic safety violations, avg 3.80s / max 7.53s.
  **Confirmed model-size limitation, not a bug**: asked for a Telugu
  greeting, replied in Devanagari-adjacent script that was not accurate
  Telugu. **Confirmed safety property, not assumed**: asked to "move
  forward," the model described the request as hypothetical/fictional
  rather than emitting anything resembling a command — consistent with
  text-only output that never reaches an actuator regardless of content.

## Detail: RAG

Two entirely separate, non-communicating RAG implementations exist:

1. **`bonbon_llm/core/rag_retriever.py`** — the one actually called by
   `llm_orchestrator_node`. Backend priority: ChromaDB (disables
   telemetry — a real 16-hour PostHog network hang was hit on Pi-2
   hardware and is documented in-code) → FAISS → NumPy brute-force
   cosine (always available, no dependency). Embeddings:
   `sentence-transformers` → deterministic MD5-hash-bucket fallback.
2. **`bonbon_data_stores/rag/chroma_store.py`** — a second, structurally
   different ChromaDB store (5 collections: knowledge/menu/faqs/
   procedures/conversations) that **nothing outside `bonbon_data_stores`
   itself imports**. Confirmed dead from the LLM's perspective by a
   repo-wide import grep. Not a bug to fix in this pass (out of scope —
   "do not touch unrelated features" — but real enough to flag loudly:
   a future engineer could reasonably assume this is the hospital-FAQ
   RAG store and be wrong).

Neither has been benchmarked on real hardware; both are `try: import
chromadb / except ImportError: degrade` — never confirmed actually
running with a real vector store.

## Detail: ASR / VAD / Wake word

| Sub-capability | Default backend | Real backend available | Confirmed hardware-verified? |
|---|---|---|---|
| VAD | `silero` (**real**, not mock) | Silero via `torch.hub.load("snakers4/silero-vad", ...)` | No |
| ASR | `mock` | faster-whisper / openai-whisper (selectable, `STTConfig.backend`) | No — and `pi2_requirements.txt` deliberately excludes openai-whisper (CUDA/triton bloat), so faster-whisper is the only real path actually meant to be installed |
| Wake word | `mock`, **disabled** (`enabled=False`) | openWakeWord (ONNX) | No |

No hardcoded language restriction in ASR code (`STTConfig.language=""`
means Whisper auto-detect) — English/Hindi/Telugu support today is
whatever faster-whisper's own multilingual model supports out of the
box, untested and unconfigured for hospital vocabulary. `sherpa-onnx` —
**zero references anywhere in the repo.**

## Detail: TTS

Piper (`en_US-lessac-medium`, English only), subprocess or Python-API
mode, `MockTTS` fallback if neither the binary nor package is present.
No Hindi/Telugu voice model configured anywhere in code — `voice_profile.py`
is architected to be "multilingual-ready" (per-language `VoiceProfile`)
but no non-English profile actually exists yet. `core/tts_health.py`
tracks latency/errors/fallback-count/queue-depth but has no CPU/temp
disable threshold (unlike the LLM guard) — TTS load is not currently
part of the Pi-2 resource-shedding decision inputs beyond its place in
the priority-order list (rank 13, `pi_efficiency_profile.yaml`).

## Detail: dashboard model status (current)

`bonbon_operator_api`'s `RobotStatus` (`models/robot_models.py`) already
surfaces: `ConversationData` (transcript text/confidence/speaker,
LLM response/status/confidence/model-name, emotion dominant/confidence/
style/operator-alert-flag), `TTSData` (speaking/text/queue-depth),
`PerformanceData` (CPU/mem/disk/load-level/degraded-flag),
`ComponentFaultData` (per-hardware-part fault registry). This is real
and live-wired (confirmed working against real Pi-2 hardware earlier
this session, per `docs/PI2_CODE_TRANSFER_REPORT.md`/dashboard
deployment reports). What's **missing** is exactly what Phase 11 of this
task is scoped to add: a unified per-model view (license status, which
runtime is active, whether a fallback is currently active and why,
benchmark results, download/installed status) — today's dashboard shows
*outputs* of the pipeline (a transcript, an LLM reply, an emotion label)
but not the *model registry* backing them.

## What Phase 1's companion agent found for vision/gesture/face/emotion/diarization

See `docs/AI_MODEL_GAP_ANALYSIS.md` for the full vision-stack findings
(Hailo model-zoo mapping, MediaPipe gesture classes, face recognition
backend, emotion/diarization packages) — gathered via a parallel audit
pass and merged there rather than duplicated in this file.
