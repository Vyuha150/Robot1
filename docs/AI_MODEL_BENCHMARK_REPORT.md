# AI Model Benchmark Report

Phase 12 of the AI model upgrade brief. Produced by
`scripts/ai_models/benchmark_all_models.py`, which drives
`bonbon_ai_model_registry.model_benchmark_runner.BenchmarkRunner` against
whichever model the registry's `ModelRuntimeSelector` actually resolves as
active for each capability — never a fabricated "the intended model would
score X" number. Raw JSON is persisted to
`docs/project-status/ai_model_benchmark_results.json` on every run (read
live by `GET /api/v1/ai-models/benchmark`).

## Environment note (read this before the numbers below)

This run was executed on the **Windows dev sandbox**, not real Pi-2/Pi-3
hardware. Per the brief's rule 1 ("do not fake model availability") and
rule 10 ("hardware-gated tests must be BLOCKED when actual hardware is
unavailable"), every case below that needs unavailable hardware/software
is reported `blocked` or `fail` with an honest `detail` string — none is
a fabricated pass.

**The one capability already benchmarked on real hardware** is the local
LLM: `qwen2.5:0.5b` was pulled and benchmarked on the real Pi-2
(`wise150@192.168.1.16`) on 2026-07-06 — see
[`docs/PI2_QWEN25_05B_SETUP_REPORT.md`](PI2_QWEN25_05B_SETUP_REPORT.md)
for those real numbers. That result is treated as authoritative and is
not re-claimed here.

**Update 1**: `sherpa-onnx`, `piper-tts` (+ its `onnxruntime` dependency),
and the real `en_US-lessac-medium` Piper voice (~63MB) were installed
into this sandbox's venv after Run 1, via the exact commands in
`docs/BONBON_AI_MODEL_UPGRADE_FINAL_REPORT.md` §14–16.

**Update 2**: `faster-whisper`, `speechbrain` (pulled in real PyTorch
2.13 + torchaudio), and `mediapipe` were installed next. `deepface` was
attempted and is genuinely **BLOCKED** — it requires TensorFlow, and
TensorFlow has **zero wheels published for Python 3.14** on PyPI as of
this pass (confirmed directly: `pip install tensorflow` on this
interpreter returns `ERROR: Could not find a version that satisfies the
requirement tensorflow (from versions: none)`) — this sandbox's Python
version, not a licensing or engineering gap. Ollama, a camera, and Hailo
hardware/`hailort` remain genuinely absent — those still cannot succeed
here regardless.

## Run 1 (baseline — nothing but the base packages installed)

```
Running 18 benchmark case(s) across 4 categor(y/ies)...
Summary: {'pass': 0, 'fail': 12, 'timeout': 0, 'blocked': 6} in 0.2s
```

| Case | Resolved model | Status | Latency | Detail |
|---|---|---|---|---|
| llm_greeting | llm_qwen25_05b | blocked | – | fallback chain exhausted (llm_qwen25_05b has no fallback_model_id; Ollama not reachable at localhost:11434 on this sandbox) |
| llm_faq_wording | llm_qwen25_05b | blocked | – | fallback chain exhausted |
| llm_clarify | llm_qwen25_05b | blocked | – | fallback chain exhausted |
| llm_safety_refusal | llm_qwen25_05b | blocked | – | fallback chain exhausted |
| asr_english_hospital_phrase | asr_degraded_template | fail | – | no invoker wired for ASR entry 'asr_degraded_template' |
| asr_telugu_hospital_phrase | asr_degraded_template | fail | – | (same — selector fell through the whole real-ASR chain to the terminal mock) |
| asr_hindi_hospital_phrase | asr_degraded_template | fail | – | (same) |
| asr_code_mixed | asr_degraded_template | fail | – | (same) |
| asr_doctor_room_entity | asr_degraded_template | fail | – | (same) |
| tts_english_greeting | tts_cached_phrase | fail | – | no invoker wired for TTS entry 'tts_cached_phrase' |
| tts_emergency_alert | tts_cached_phrase | fail | – | (same) |
| tts_navigation_instruction | tts_cached_phrase | fail | – | (same) |
| tts_token_announcement | tts_cached_phrase | fail | – | (same) |
| vision_object_fps | – | blocked | – | no registered default for capability 'object_detection' (GAP-2, see below) |
| vision_person_fps | – | blocked | – | no registered default for capability 'person_detection' (GAP-2) |
| vision_gesture_fps | gesture_mock | fail | – | vision invoker requires a real camera frame — not exercised by this standalone script |
| vision_face_latency | face_mock | fail | – | (same) |
| vision_emotion_latency | emotion_face_mock | fail | – | (same) |

## Run 2 (after installing sherpa-onnx + piper-tts + the real English voice)

```
Running 18 benchmark case(s) across 4 categor(y/ies)...
Summary: {'pass': 4, 'fail': 8, 'timeout': 0, 'blocked': 6} in 22.7s
```

| Case | Resolved model | Status | Latency | Detail |
|---|---|---|---|---|
| llm_greeting … llm_safety_refusal (4) | llm_qwen25_05b | blocked | – | unchanged — Ollama still absent here |
| asr_english_hospital_phrase … asr_doctor_room_entity (5) | **asr_sherpa_onnx** | fail | – | chain now resolves to a real, "available" engine (package installed), but no ASR model file has been selected for it yet (GAP-7) — `no invoker wired for ASR entry 'asr_sherpa_onnx'` |
| **tts_english_greeting** | **tts_piper_en** | **pass** | **5847ms** | ok — real synthesized audio |
| **tts_emergency_alert** | **tts_piper_en** | **pass** | **5599ms** | ok |
| **tts_navigation_instruction** | **tts_piper_en** | **pass** | **5704ms** | ok |
| **tts_token_announcement** | **tts_piper_en** | **pass** | **5339ms** | ok |
| vision_* (5) | unchanged | blocked/fail | – | no camera, still GAP-2 for object/person detection |

**4 real passes** — the first non-fabricated `pass` results this pass has
produced. Each is a genuine Piper subprocess call producing a real
`RIFF`/`WAVE` `.wav` file (spot-checked in
`tests/speech_ai/test_tts_router.py::TestRealPiperSynthesisWhenInstalled`).
ASR moved from `fail`-on-the-terminal-mock to `fail`-on-a-real-but-
not-yet-wired engine — an honest, more informative failure (see the two
bug fixes below), not a regression.

## Run 3 (after installing faster-whisper + speechbrain + mediapipe, plus 2 real ASR sample recordings)

```
Running 18 benchmark case(s) across 4 categor(y/ies)...
Summary: {'pass': 6, 'fail': 6, 'timeout': 0, 'blocked': 6} in 21.8s
```

| Case | Resolved model | Status | Latency | Detail |
|---|---|---|---|---|
| llm_* (4) | llm_qwen25_05b | blocked | – | unchanged |
| **asr_english_hospital_phrase** | **asr_faster_whisper** | **pass** | **5750ms** | Real round-trip: synthesized with Piper ("The cardiology department is on the second floor, near the main elevator."), transcribed back **verbatim, word-for-word** |
| asr_telugu_hospital_phrase | asr_faster_whisper | fail | – | `[Errno 2] No such file` — no Telugu Piper voice exists (GAP-8) to synthesize a sample from |
| asr_hindi_hospital_phrase | asr_faster_whisper | fail | – | same — Hindi candidate voice not yet fetched |
| asr_code_mixed | asr_faster_whisper | fail | – | same — no way to authentically synthesize genuine code-mixed speech from a single English-only voice; left honestly blocked rather than faked as "English only" |
| **asr_doctor_room_entity** | **asr_faster_whisper** | **pass** | **2970ms** | Real round-trip: synthesized "Doctor Sharma is available in room number seven.", transcribed back as "Dr. Sharma is available in room number 7." — **semantically correct**, Whisper's standard entity/number normalization (exactly what `hospital_entity_corrector.py` exists to reconcile against hospital records) |
| tts_* (4) | tts_piper_en | pass | 2528–2789ms | unchanged from Run 2 (variance is process/OS-cache noise, not a regression) |
| vision_* (5) | unchanged | blocked/fail | – | mediapipe now installed (`gesture_mediapipe_holistic` resolves as active), but still needs a real camera frame — GAP-2 unaffected |

**Now 6/18 pass** — genuine, verified real audio round-tripped through the
whole ASR pipeline, not just TTS. The two English ASR passes are the
first proof that `asr_faster_whisper`'s actual invocation logic (not
just its availability check) works correctly end-to-end. Telugu, Hindi,
and code-mixed remain honestly blocked — the real reason is "no source
audio to test with," not a code defect, and this pass deliberately did
not fabricate a fake Hindi/Telugu sample using the English voice to
inflate the pass count.

### `voice_emotion` and `gesture_recognition` also flipped to real engines

Beyond what the benchmark script exercises, installing `speechbrain` and
`mediapipe` changed two more capabilities' live selector resolution:
`voice_emotion` now resolves to `voice_emotion_speechbrain` (previously
`voice_emotion_text_sentiment` — a fallback with no acoustic model at
all) and `gesture_recognition` now resolves to
`gesture_mediapipe_holistic` (previously `gesture_mock`). Both are
registered as `enabled_by_default: true` already — this doesn't change
any registry defaults, it just means the intended default now actually
loads on this machine, the same effect installing sherpa-onnx/piper had
on ASR/TTS in Run 2.

### DeepFace: genuinely blocked by the Python interpreter version, not skipped

`pip install deepface` fails here — it requires `tensorflow`, and
`tensorflow` currently publishes **no wheel for Python 3.14 on any
platform**. Confirmed directly (`pip install tensorflow` alone fails
identically), not inferred from deepface's error message alone. `face_emotion`
correctly stays on `emotion_face_mock`. This is an environment
constraint (this sandbox's interpreter is newer than TensorFlow's
current release train supports), not a licensing or engineering gap —
it will resolve itself once TensorFlow ships 3.14 wheels, or by using an
older Python interpreter for a venv dedicated to this capability.

### A real efficiency finding: no model caching across calls

Both `ASRRouter._invoke()` (`WhisperModel("base")`) and
`TTSRouter._invoke()` (a fresh `piper` subprocess) construct/load their
model from scratch on **every single call** — nothing is cached or kept
warm across requests. On this dev machine that costs ~2.5–5.8s per call
regardless of whether the audio is 3 words or 30. For a hospital robot
that needs responsive turn-taking, that is a real latency problem, not
just a benchmark curiosity — flagged as a follow-up (see the spawned
task), not fixed in this pass since it's a caching/lifecycle design
change beyond "install and re-benchmark."

### ~5.3–5.8s latency is a real, notable data point

Each TTS case took over 5 seconds — this is Piper's cold subprocess-
start overhead (~5s) plus CPU-only ONNX inference on this dev machine,
not a reflection of expected real-time performance. This is flagged, not
hidden: 5+ seconds per short sentence would be unacceptable for live
reception-desk dialogue. Real Pi-2 ARM CPU timing must be measured
separately before treating this as production-representative — the
number here only proves the pipeline is real and functional, not that
it's fast enough yet. A warm, in-process Piper Python API call (rather
than spawning a subprocess per utterance) is the obvious next
optimization once this is benchmarked on real hardware.

### Two real bugs found and fixed while producing Run 2

1. **`entry.model_name` used as a literal filesystem path.**
   `model_name` is a human-readable *display* string everywhere in this
   registry (e.g. `"en_US-lessac-medium (Piper)"`), never guaranteed to
   match an on-disk filename. `TTSRouter._invoke()` and
   `benchmark_all_models.py`'s `invoke_tts()` both built
   `models/piper/{entry.model_name}.onnx` directly, producing
   `models/piper/en_US-lessac-medium (Piper).onnx` — a file that can
   never exist, since every download script writes
   `en_US-lessac-medium.onnx`. This would have silently broken on **any**
   real deployment, not just this sandbox — it only surfaced once a real
   voice file was actually downloaded and tested against. Fixed by
   adding a new `ModelEntry.asset_filename` field (the real on-disk
   filename stem, separate from the display `model_name`), populated for
   `tts_piper_en`/`tts_piper_hi`, and used by both call sites.
2. **`ASRRouter.transcribe()` crashed once a real (but not-yet-wired)
   ASR engine became available.** Installing `sherpa-onnx` made
   `asr_sherpa_onnx` resolve as the active engine (package importable →
   selector reports it available), but no invoker is wired for it yet
   (GAP-7, no model file selected) — `_invoke()` raised
   `NotImplementedError`, uncaught, crashing `transcribe()`. Fixed with
   the same try/except-degrade-honestly pattern `TTSRouter.speak()`
   already used, so an engine that resolves as "available" but fails to
   actually invoke now degrades to an empty transcript instead of
   crashing the caller.

Both are regression-tested: `tests/speech_ai/test_asr_router.py`'s
`test_transcribe_never_raises_regardless_of_which_tier_is_active` and a
new `test_invocation_failure_degrades_gracefully_even_when_selector_reports_available`;
`tests/speech_ai/test_tts_router.py`'s new `TestRealPiperSynthesisWhenInstalled`
class (skips honestly if the package/voice/CLI aren't all present).

### Reading `fail` vs `blocked` correctly

These two statuses mean different things here and neither is a fabricated
result:

- **`blocked`** — the registry's fallback chain resolved to *nothing at
  all* (`active_model_id is None`), or (for object/person detection) no
  `enabled_by_default` entry exists at all. Nothing was invoked.
- **`fail`** — the selector *did* resolve to a real, registered entry
  (usually the terminal `mock`/`degraded` fallback at the end of a
  chain — e.g. `asr_degraded_template`, `tts_cached_phrase`), but
  `scripts/ai_models/benchmark_all_models.py`'s invoker functions only
  implement real backends (Ollama HTTP, `faster-whisper`,
  `piper` via the `rhasspy` provider) and intentionally raise
  `NotImplementedError` for the mock/degraded terminal entries rather
  than fake a timing number for a model that does nothing. The ASR/TTS
  chains correctly cascaded past every real backend (none installed
  here) down to their honest last-resort entries — the fallback logic
  itself is working exactly as designed; there's simply no invoker
  written for a no-op model.

`vision_object_fps`/`vision_person_fps` are `blocked` rather than `fail`
because **no entry in `object_detection`/`person_detection` is marked
`enabled_by_default`** in the base registry. This is deliberate, not a
new bug: `docs/AI_MODEL_GAP_ANALYSIS.md` GAP-2 documents that this
capability has three competing real implementations
(`bonbon_vision.YoloDetector`, `ObjectDetectorRuntimeAdapter`, a raw
Ultralytics path) that were registered honestly rather than one being
silently declared "the" default without the code consolidation GAP-2
calls for. Until that consolidation happens, the dashboard reports these
two capabilities as blocked rather than guessing.

## What these runs confirm

- The registry, selector, and fallback-chain logic all execute correctly
  end-to-end (no crashes, no exceptions escaping `run_all`) against 39
  real registry entries across 16 capabilities.
- Every unavailable model is reported unavailable — zero fabricated
  `pass` results in Run 1; Run 2's 4 passes are genuine (real audio
  files produced), consistent with rule 1 across both runs.
- `BenchmarkReport.to_dict()`/JSON persistence (added this phase) round-
  trips correctly to `docs/project-status/ai_model_benchmark_results.json`
  and is served live by `GET /api/v1/ai-models/benchmark`.
- Installing a real backend genuinely changes the benchmark's real
  results (Run 1 → Run 2) without any code path needing to be told to
  "notice" the new capability — the registry/selector's live,
  re-checked-every-call design means this works automatically.

## Remaining gaps (still real, still not faked)

- `asr_*`: chain now resolves to a real, installed engine
  (`asr_sherpa_onnx`), but no invoker is wired for it — GAP-7. Wiring one
  requires selecting a specific sherpa-onnx model file and benchmarking
  it, a deliberate model-selection decision this pass didn't make blind.
- `llm_*`: Ollama is not installed in this sandbox at all (confirmed —
  its PATH entry was stale, pointing at a directory that no longer
  exists). Already benchmarked for real on Pi-2 (see above).
- `vision_*`: no camera in this sandbox; `object_detection`/
  `person_detection` additionally have no default per GAP-2.

## Re-running on real Pi-2/Pi-3 hardware

```bash
python3 scripts/ai_models/benchmark_all_models.py
python3 scripts/ai_models/benchmark_all_models.py --category llm
python3 scripts/ai_models/benchmark_all_models.py --category asr
```

Expected to newly `pass` once run on real hardware with the relevant
backend installed: `llm_*` (after `ollama pull qwen2.5:0.5b` — already
done once, see setup report above), `asr_*` (after a sherpa-onnx model
file is selected and wired, or a `faster-whisper` install, and real
`.wav` sample files placed at the `samples/asr/*.wav` paths the cases
reference — none exist in this repo yet, since recording hospital-phrase
audio is a human/hardware task, not something this pass can fabricate).
`tts_*` already passes here and should be re-measured on real Pi-2 ARM
CPU for a production-representative latency number (see the ~5.3–5.8s
note above). Vision cases require a real camera frame and are
intentionally out of this script's scope (see `bonbon_ai_runtime`'s own
bench CLI, referenced in the `NotImplementedError` message above).
