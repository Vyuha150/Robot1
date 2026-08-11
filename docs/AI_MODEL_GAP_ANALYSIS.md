# AI Model Gap Analysis

Prioritized, actionable gaps found in Phase 1's audit
(`docs/AI_MODEL_CURRENT_AUDIT.md`). Each gap states what's missing, why
it matters, and the recommended fix — separating what this pass's
registry work fixes structurally from what needs a follow-up engagement
with real hardware access.

## GAP-1 (NEW FINDING, HIGH PRIORITY) — Two "default" emotion backends aren't actually installed

`bonbon_affective_ai`'s code defaults to **DeepFace** (face emotion) and
**SpeechBrain** (voice emotion) — both are the active backend, both are
warmed up on node activation. **Neither package appears in
`requirements/pi2_requirements.txt`**, the one real Docker-build install
manifest for this hardware generation. `pi2_requirements.txt` even
explains *why* DeepFace was excluded — but that reasoning
(`insightface` already covers face *recognition*) doesn't apply to face
*emotion*, a different DeepFace use inside a different package the
requirements file's author likely wasn't cross-referencing.

**Consequence**: on the actual Pi-2 Docker deployment, both of these
"default, active" backends will hit `ImportError` and silently degrade
to mock — the code's own assumption that they're live is currently
false in the one environment that matters. This was never caught because
no test or benchmark has exercised `bonbon_affective_ai` against the
real `pi2_requirements.txt` install set.

**Recommended fix**: add `deepface` and `speechbrain` to
`pi2_requirements.txt`, OR change the registry's default fallback
policy to correctly report `face_emotion`/`voice_emotion` as
`MOCK_ONLY` until that's done. This pass's registry (Phase 2) takes the
second option — it reports the true installed state honestly rather
than trusting the code's own default-backend selection, and flags the
requirements-file fix as the concrete next step.

## GAP-2 (HIGH PRIORITY) — Object/person detection has 3 duplicate implementations

`bonbon_vision.YoloDetector`, `bonbon_vision.ObjectDetectorRuntimeAdapter`,
and `bonbon_perception.YoloPersonDetector` are three independent
`ultralytics`/`torch.hub` integrations. Only one of the three
(`ObjectDetectorRuntimeAdapter`) goes through `bonbon_ai_runtime`'s
Hailo/CPU/mock selector — and it's opt-in, not the default. This is the
same class of concern rule 8 names for camera/mic pipelines, applied to
detector pipelines: three code paths that could disagree about what's
detected, three sets of resource usage, three places a future bug fix
has to be applied.

**Recommended fix (not undertaken in this pass — real code surgery
across two packages, higher risk than registry work)**: consolidate onto
`ObjectDetectorRuntimeAdapter` as the one detector, make it the default
backend, delete or clearly deprecate the other two. **This pass's
registry** instead registers all three honestly as separate entries so
the duplication is visible on the dashboard rather than hidden, and
marks only the `bonbon_ai_runtime`-routed one as `enabled_by_default:
true` going forward for *new* deployments — existing bringup launch
files are untouched (out of scope for a registry-building pass).

## GAP-3 (HIGH PRIORITY) — No person-enrollment/consent mechanism for face recognition

Both face-recognition implementations are read-only lookups against a
pre-populated embedding store (`embeddings.pkl` / SQLite table) — no
code path anywhere lets a person consent to enrollment, and no code
writes a face embedding at runtime. This actually satisfies "no raw face
storage by default" and "unknown people remain anonymous" by omission,
but it means the "known person" feature literally cannot be used in
production without an out-of-band, undocumented process to populate the
embedding store. **Recommended**: out of scope for this pass (a real
enrollment UI/consent-flow is a product feature, not a model-registry
concern) — flagged here so it isn't silently assumed to exist.

## GAP-4 (MEDIUM) — LLM code default is `llama3.2:3b`, not `qwen2.5:0.5b`

Already independently flagged once in `docs/THREE_PI_CURRENT_ARCHITECTURE_AUDIT.md`.
The correct model only applies via the Pi-2 launch/compose override.
**Recommended fix, done in this pass**: the new registry's
`pi_ai_hat_plus_2_profile.yaml` and `offline_open_source_profile.yaml`
both set `qwen2.5:0.5b` as the enabled-by-default LLM entry, and
`model_runtime_selector.py` reads from the registry rather than
`bonbon_llm`'s own hardcoded default — so any consumer that goes through
the new registry gets the right model regardless of the underlying
package's own default. The underlying `llm_config.py` default is left
unchanged (out of scope — changing a shipped package's default touches
more than this registry work should).

## GAP-5 (MEDIUM) — `bonbon_data_stores/rag/` is dead code

A second, complete ChromaDB RAG implementation (5 collections) that
nothing imports outside its own package. Not fixed (removing code is a
larger call than this pass should make unilaterally), but registered
honestly: the new registry's RAG entry points at `bonbon_llm`'s
`rag_retriever.py` only, and this doc records the duplicate for whoever
next touches RAG so they don't assume it's the active one.

## GAP-6 (MEDIUM) — ASR/wake-word default to mock; VAD is the only real default

`STTConfig.backend="mock"` and `WakeWordConfig.enabled=False` out of the
box — real backends (faster-whisper, openWakeWord) exist and are
correctly excluded-vs-included in `pi2_requirements.txt` (faster-whisper
yes, openai-whisper deliberately no), but nothing turns them on by
default. **Recommended fix, done in this pass**: registry profiles
(`pi_ai_hat_plus_2_profile.yaml`) mark `asr_faster_whisper` and
`wake_word_openwakeword` as `enabled_by_default: true`, with the router
(Phase 6) selecting them ahead of the mock fallback — again without
touching `bonbon_speech`'s own package-level defaults, which stay
conservative on purpose for standalone package use.

## GAP-7 (LOW) — `sherpa-onnx` and `whisper.cpp` have zero references anywhere

Both are named in this task's own Phase 3 spec as preferred/benchmark-tier
ASR options; neither exists in the repo today. **Recommended**: register
both in the new model registry as `enabled_by_default: false` (not
installed, not yet benchmarked against the already-working
faster-whisper choice) — see the download/license plan for exactly what
would be needed to add them, and the gap analysis's own recommendation:
faster-whisper is *already* one of this task's own sanctioned
open-source ASR fallbacks ("faster-whisper only if Pi performance
allows") and already has real Pi-2-appropriate reasoning behind its
selection in `pi2_requirements.txt` (CTranslate2 int8, no CUDA drag-in)
— sherpa-onnx/whisper.cpp are worth benchmarking against it before
displacing it, not assumed superior by default.

## GAP-8 (LOW) — No Hindi/Telugu TTS voice configured anywhere

Only `en_US-lessac-medium` (Piper) exists. `voice_profile.py` is
architected to support more languages but none are wired. **Recommended**:
register Piper's Hindi/English-multilingual community voices (real,
open, MIT-licensed, downloadable — see license plan) as
`enabled_by_default: false` pending an actual download+benchmark pass on
real hardware; register Sarvam Edge TTS as the preferred path *if*
access is ever obtained (currently: no evidence of access, see Sarvam
section below).

## GAP-9 (LOW) — Gesture taxonomy: 2 of 16 requested classes have dead detection logic, 2 don't exist

`come_here`'s detector always returns `False` (explicit placeholder,
"requires multi-frame temporal analysis"); `go_away` is referenced only
in downstream intent-mapping tables with no detector ever producing it;
`pointing_at_object` and `namaste/folded_hands` have zero code anywhere.
**Recommended**: registered honestly in the new registry's gesture
capability entry as `supported_classes` (10) vs `configured_but_not_detected`
(2: come_here, go_away) vs `not_implemented` (2: pointing_at_object,
namaste) — real implementation work for these 4 is out of scope for a
registry-building pass (it's `bonbon_gesture` feature work, not model
selection/routing).

## GAP-10 (INFORMATIONAL) — Hailo Model Zoo mapping is scaffolding only

`config/runtime/model_runtime.yaml` references generic filenames, not
real Hailo Model Zoo model identifiers, and no `.hef` file exists
anywhere in the repo. This is expected (models are deploy-time-injected,
not repo-committed — correct practice, large binary files don't belong
in git) but means "Hailo YOLO model if available" in this task's Phase 7
brief is, today, **entirely hypothetical** until someone with a real AI
HAT+2 and Hailo Model Zoo access compiles and deploys real `.hef` files.
Registered as `HARDWARE_BLOCKED` in the new registry, not `MISSING` —
the gap isn't a missing decision, it's missing hardware access.

## GAP-11 (INFORMATIONAL) — Sarvam AI: zero prior integration, no evidence of access

Confirmed by two independent repo-wide greps (this session's own audit,
plus the LLM/speech research agent's audit): zero mentions of "Sarvam"
anywhere in `bonbon_robot_ai`. No package, no API key reference, no
documentation. Per rule 3/12, Sarvam is only used if official access
exists — it does not, in this environment. The new `bonbon_sarvam_adapter`
(Phase 5) is built to *detect* access if it's ever added, and honestly
reports `unavailable` today — it does not invent a download URL or
pretend access exists.

## Summary — what this pass fixes vs. defers

| Gap | Fixed by registry/router work this pass | Deferred (needs code surgery / hardware / product decision) |
|---|---|---|
| GAP-1 (DeepFace/SpeechBrain not installed) | ✅ reported honestly, not silently assumed active | requirements.txt fix |
| GAP-2 (3 detector implementations) | ✅ registered separately, dashboard-visible | consolidation |
| GAP-3 (no enrollment/consent) | — | product feature |
| GAP-4 (LLM default model) | ✅ registry default corrected | package-level default |
| GAP-5 (dead RAG code) | ✅ registry points at the real one | code removal |
| GAP-6 (ASR/wake-word mock default) | ✅ registry enables real backends by default | package-level default |
| GAP-7 (sherpa-onnx/whisper.cpp absent) | ✅ registered, not installed, not auto-downloaded | benchmark decision |
| GAP-8 (no Hindi/Telugu TTS) | ✅ registered as available-not-enabled | download + benchmark |
| GAP-9 (gesture taxonomy gaps) | ✅ registered honestly | `bonbon_gesture` feature work |
| GAP-10 (Hailo Model Zoo scaffolding) | ✅ registered as HARDWARE_BLOCKED | real Hailo hardware + compiled `.hef` |
| GAP-11 (Sarvam access) | ✅ adapter detects honestly | official Sarvam access |
