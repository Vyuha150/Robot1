# Speech AI Upgrade Report (ASR)

Phase 6/14. Covers `bonbon_speech_ai`'s ASR side: `asr_router.py`,
`language_detector.py`, `transcript_normalizer.py`,
`hospital_entity_corrector.py`, and `speech_pipeline.py`. TTS is covered
separately in `docs/TTS_UPGRADE_REPORT.md`.

## Pipeline

```
audio in → VAD/wake-word (existing bonbon_speech nodes, not duplicated)
         → ASRRouter.transcribe()
         → language_detector.detect() (if ASR didn't report a language)
         → transcript_normalizer
         → hospital_entity_corrector
         → downstream (LLM / RAG / deterministic FAQ / behavior engine)
```

`ASRRouter` does **not** run continuous ASR itself — callers gate calls on
a real VAD/wake-word event first, avoiding a second, duplicate audio
pipeline (rule 8).

## ASR priority chain

`asr_sarvam_edge → asr_faster_whisper → asr_sherpa_onnx → asr_whisper_cpp
→ asr_degraded_template`, resolved live on every call by
`ModelRuntimeSelector` + `FallbackPolicy` against the real, checked-in
`config/models/model_registry.yaml` — never a hardcoded chain duplicated
in this package.

- **Sarvam Edge** — first, per rule 12, but only when
  `bonbon_sarvam_adapter` confirms real access (see
  `docs/SARVAM_INTEGRATION_REPORT.md`). Not active in this environment.
- **faster-whisper** — the open-source default (`asr_faster_whisper`,
  MIT). Not installed in this dev sandbox; real install command is
  `scripts/ai_models/install_sherpa_onnx.sh`'s sibling
  (`pip install faster-whisper`, documented in
  `docs/AI_MODEL_DOWNLOAD_AND_LICENSE_PLAN.md`).
- **sherpa-onnx**, **whisper.cpp** — further open-source fallbacks.
- **asr_degraded_template** — terminal, always-available mock: returns an
  empty transcript rather than crashing, so the UI can fall back to
  typed/touch input.

## Two bugs found and fixed this pass

1. **Terminal-mock guard gap.** `ASRRouter.transcribe()`'s guard
   originally only checked `decision.active_model_id is None`. But the
   terminal `asr_degraded_template` entry is a **real registered entry**
   with `hardware_target: mock` — the generic availability checker
   (`_check_mock_available` always returns `True`) correctly resolves it
   as "active," so `active_model_id` is never actually `None` in the
   fully-exhausted case; it's `"asr_degraded_template"`. The old guard
   missed this, so `_invoke()` fell through to
   `ValueError("no invoker registered for ASR model_id 'asr_degraded_template'")`
   — a crash, not a graceful degrade. Fixed by widening the guard to
   also treat `"asr_degraded_template"` as the terminal case.
2. **A real engine becoming available exposed an uncaught crash.**
   Installing `sherpa-onnx` (see
   `docs/AI_MODEL_BENCHMARK_REPORT.md`'s Run 2) made the chain resolve
   to `asr_sherpa_onnx` instead of the terminal mock — a genuinely
   "available" entry (package importable) with no invoker wired yet
   (GAP-7, no model file selected). `_invoke()` raised
   `NotImplementedError`, and unlike `TTSRouter.speak()`, `transcribe()`
   didn't catch it — a real crash the moment a real backend package
   showed up, exactly the kind of regression only surfaced by actually
   installing something rather than reasoning about it. Fixed by
   wrapping the `_invoke()` call in `transcribe()` in the same
   catch-and-degrade pattern `TTSRouter.speak()` already used: any
   invocation failure now returns an honest empty transcript rather than
   propagating.

Both regression-tested in `tests/speech_ai/test_asr_router.py`:
`test_transcribe_never_raises_regardless_of_which_tier_is_active` (checks
against whatever `active_engine()` actually resolves to on the running
machine, not a hardcoded engine id) and
`test_invocation_failure_degrades_gracefully_even_when_selector_reports_available`
(structural — forces `_invoke` to raise via mocking, independent of what
happens to be installed).

## A third bug found and fixed (India-readiness audit round)

`speech_pipeline.py` computed `language_detector.detect()`'s
`is_code_mixed` flag but never passed it anywhere — `transcript_normalizer
.normalize()` only had a `language_code` parameter, and applied
English-digit-word conversion (`"seven"` → `"7"`) only when
`language_code == "en"` exactly. For a Hindi-dominant code-mixed
utterance like "mera room number seven hai," `language_code` resolves to
`"hi"` (Hindi is the majority script), so `"seven"` never got converted —
`hospital_entity_corrector`'s `_ROOM_PATTERN` (which requires `\d{1,4}`)
then silently failed to extract the room number, with no error anywhere
in the chain. This is exactly the kind of real-world phrasing code-mixed
Indian speech to a hospital robot commonly produces. Fixed by threading
`is_code_mixed` through `normalize()`: when set, digit-word conversion
runs regardless of the dominant language, and filler-word stripping uses
the union of all languages' filler sets rather than just the dominant
one's. 11 new tests in `tests/speech_ai/test_transcript_normalizer.py`,
including one that reproduces the pre-fix failure
(`test_room_number_extraction_fails_without_code_mixed_flag`) so a
regression here is caught immediately.

## Known architecture gap: two disconnected speech stacks (not fixed this round)

`bonbon_speech_ai` (this report's subject: `asr_router.py` /
`tts_router.py` / `language_detector.py` / `transcript_normalizer.py` /
`hospital_entity_corrector.py` / `speech_pipeline.py`) is library code
with no ROS2 node or launch file of its own, and is **never imported by**
`bonbon_speech/nodes/speech_node.py` — the actual live ROS2 node wired to
VAD/wake-word/STT via `WhisperSTT`. Confirmed by grep: no cross-reference
either direction. This means everything in this report — the ASR
priority chain, the code-mix fix above, all of it — is real, tested, and
correct, but **not yet running in the live speech pipeline**; it's
exercised only by direct unit tests today.

Wiring `bonbon_speech_ai` into `speech_node.py` is an architecture
decision (which of two parallel implementations becomes "the" production
ASR/TTS path) deliberately left for an explicit choice rather than done
silently as part of this audit — same posture as the Sarvam
licensing/access blocker: flagged, not fabricated or worked around.

## Language detection (`language_detector.py`)

Deterministic, no ML model, no network call: Devanagari codepoints
(U+0900–U+097F) → Hindi, Telugu codepoints (U+0C00–U+0C7F) → Telugu,
otherwise Latin-script → English. Code-mixed speech resolved by majority
script with an `is_code_mixed` flag preserved for downstream per-token
handling, not collapsed into one guessed language. 8 tests in
`tests/speech_ai/test_language_support.py`, including a realistic
Hindi+English code-mixed hospital phrase.

## Status on this environment

`asr_faster_whisper`/`asr_sherpa_onnx`/`asr_whisper_cpp` all report
unavailable (not installed) — chain correctly cascades to
`asr_degraded_template`, verified live in
`docs/AI_MODEL_BENCHMARK_REPORT.md`'s benchmark run. This is the honest,
correct behavior for this machine, not a defect.

## Verdict: **PARTIAL** — router/fallback/language-detection/code-mix-normalization logic is complete, tested, and correct. Real transcription requires installing one real ASR backend and running on Pi-2 hardware with a real microphone (ReSpeaker XVF3800, per the BOM). Separately, `bonbon_speech_ai` is not yet wired into the live `bonbon_speech` ROS2 node — see "Known architecture gap" above; that decision is flagged for the user, not made here.
