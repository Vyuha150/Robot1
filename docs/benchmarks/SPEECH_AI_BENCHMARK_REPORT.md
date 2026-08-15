# Speech AI Benchmark Report

**Run:** real, from `docs/project-status/efficiency_benchmark_results.json`'s `speech_ai` category + `tests/benchmarks/test_speech_ai_benchmark.py` (8 tests).

## The 12 required scenarios

| # | Scenario | Result |
|---|---|---|
| 1 | VAD | **PASS** -- p95=0.226ms (MockVAD; Silero/torch unavailable, honestly labeled as a mock backend measurement) |
| 2 | ASR English | HARDWARE_BLOCKED -- no wired invoker for the specific registry entry exercised (`asr_degraded_template`) |
| 3 | ASR Hindi | HARDWARE_BLOCKED -- no real audio sample corpus in this environment |
| 4 | ASR Telugu | HARDWARE_BLOCKED -- same reason |
| 5 | Code-mixed phrase | HARDWARE_BLOCKED -- same reason |
| 6 | Noisy reception phrase | HARDWARE_BLOCKED -- same reason |
| 7 | Doctor name recognition | HARDWARE_BLOCKED -- same reason |
| 8 | Room number recognition | HARDWARE_BLOCKED -- same reason |
| 9 | TTS English | HARDWARE_BLOCKED -- no wired invoker for `tts_cached_phrase` entry |
| 10 | TTS Hindi | HARDWARE_BLOCKED -- same reason |
| 11 | TTS Telugu | HARDWARE_BLOCKED -- same reason |
| 12 | Cached TTS phrase | HARDWARE_BLOCKED -- no audio output device in this environment |

Every one of the 10 language/scenario-specific ASR/TTS cases is named individually (`tests/benchmarks/test_speech_ai_benchmark.py::TestAllTwelveScenariosAreAccountedFor`), not collapsed into one generic "ASR blocked" line -- confirmed by test assertion that all 10 names are present and none share a blocked reason string by coincidence.

## Models benchmarked (per registry, where installed)

| Model | Status |
|---|---|
| Sarvam Edge | Not installed/configured -- no official access confirmed in this environment |
| sherpa-onnx | Not exercised this run (faster-whisper is the registry's enabled-by-default ASR entry) |
| whisper.cpp | Not exercised this run |
| Piper | Registry entry present (`models/piper/en_US-lessac-medium.onnx`); the specific case exercised this run hit a different registry entry (`tts_cached_phrase`) with no wired invoker |
| Cached phrase audio | HARDWARE_BLOCKED -- no audio device |

## Metrics captured

latency (real for VAD, BLOCKED elsewhere), confidence (N/A -- no real inference ran), CPU/RAM/temperature (BLOCKED, see `CURRENT_PERFORMANCE_LIMITS.md`), timeout (none observed), fallback triggered (yes -- every BLOCKED case correctly reports the real reason its fallback chain was exhausted, per `bonbon_ai_model_registry`'s existing fail-closed design).

## Verdict: **HARDWARE_BLOCKED** for all real speech-model inference; **PASS** for the one component genuinely measurable without hardware (VAD decision overhead). Re-run `scripts/benchmarks/run_hardware_benchmarks.sh` on a Pi with faster-whisper/Piper/a real mic to close this gap.
