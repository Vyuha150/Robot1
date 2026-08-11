# TTS Upgrade Report

Phase 6/14. Covers `bonbon_speech_ai.tts_router.TTSRouter` — text-to-
speech selection, the hospital-phrase cache, and the "TTS must not block
safety" rule.

## Priority chain

`tts_sarvam_edge → tts_piper_en → tts_sherpa_onnx → tts_cached_phrase →
tts_text_only`, resolved live against `config/models/model_registry.yaml`.

- **Sarvam Edge** — first per rule 12, gated on real confirmed access
  (see `docs/SARVAM_INTEGRATION_REPORT.md`); not active here.
- **Piper (English)** — open-source default (`tts_piper_en`, MIT +
  CC0/MIT voice card). A separate `tts_piper_hi` entry exists for Hindi
  (Piper voices are per-language assets, not one multilingual model).
- **sherpa-onnx** — further open-source fallback.
- **`tts_cached_phrase`** — pre-recorded audio for the 6 named hospital
  phrases (`HOSPITAL_PHRASE_CACHE_KEYS`: welcome_greeting, token_called,
  please_wait, follow_me, emergency_staff_alert, navigation_arrived).
  Files live under `models/tts_cache/<lang>/<key>.wav` — this package
  only names which keys are expected to exist, it does not itself contain
  the audio assets.
- **`tts_text_only`** — terminal: display-only fallback, no audio.

## Rule: "TTS must never block safety"

`speak()` wraps synthesis in a bare `except Exception` and always
degrades to a text-only `SpeechResult` rather than propagating an
exception into a safety-relevant call path. Verified in
`tests/speech_ai/test_tts_router.py::test_speak_never_raises_regardless_of_which_tier_is_active`
and (structurally, regardless of environment)
`test_synthesis_failure_degrades_to_text_only_even_when_selector_reports_available`.

## Known gap: no Telugu TTS voice registered (GAP-8)

`docs/AI_MODEL_GAP_ANALYSIS.md` GAP-8: no Piper Telugu voice has been
identified/downloaded yet. Telugu TTS requests fall through to Sarvam (if
access exists) or the English/cached-phrase fallback otherwise — this is
registered and reported honestly, not silently defaulted to a wrong-
language voice.

## Status on this environment — UPDATED: real synthesis now verified

Originally, no `piper` binary and no `sherpa_onnx` package were
installed → chain cascaded to `tts_cached_phrase`/`tts_text_only`.

**Since then**, `piper-tts` was installed (`bash
scripts/ai_models/install_piper_tts.sh`) and the real English voice
(`en_US-lessac-medium.onnx`, ~63MB, from
`huggingface.co/rhasspy/piper-voices`) was downloaded. `TTSRouter` now
resolves to and successfully invokes `tts_piper_en` end-to-end,
producing real, valid `.wav` audio (`RIFF`/`WAVE` header confirmed) —
verified for 4 real hospital phrases (greeting, emergency alert,
navigation instruction, token announcement) in
`docs/AI_MODEL_BENCHMARK_REPORT.md`'s Run 2, all `pass`, ~5.3–5.8s
latency each (subprocess cold-start + CPU ONNX inference on this
dev machine — not yet measured on real Pi-2 ARM CPU, flagged as a real
performance concern to verify there, not hidden here).

**Real bug found and fixed while verifying this**: `TTSRouter._invoke()`
built the voice file path from `entry.model_name`
(`"en_US-lessac-medium (Piper)"`, a human-readable *display* string used
identically across the whole registry) instead of the real on-disk
filename (`en_US-lessac-medium.onnx`, no parenthetical suffix) — a path
that could never exist, on any deployment, not just this sandbox. Fixed
by adding a dedicated `ModelEntry.asset_filename` field, separate from
the display `model_name`. Regression-tested in
`tests/speech_ai/test_tts_router.py::TestRealPiperSynthesisWhenInstalled`.

Hindi (`tts_piper_hi`) is registered with its candidate `asset_filename`
(`hi_IN-pratham-medium`, matching `install_piper_tts.sh --with-hindi`'s
target) but that voice has not been fetched/benchmarked in this pass —
remains a documented, honest gap, not silently assumed working by
association with the English fix.

## Verdict: **PASS** (English TTS — real synthesis verified end-to-end, router/fallback/safety-degrade logic complete and tested) / **PARTIAL** (Hindi — voice candidate identified, not yet fetched) / **BLOCKED** (Telugu — GAP-8, no voice exists). A real 4Ω 10W speaker + PAM8610 amp (Pi-2, per the BOM) is still needed to actually play the synthesized audio on the robot; latency must be re-measured on real Pi-2 ARM hardware before treating ~5.5s as production-representative.
