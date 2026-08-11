# AI Model Download & License Plan

Every candidate model this task's Phase 3 strategy names, with license
status, approximate size, and whether this pass auto-downloads it. Rule
2 ("do not download without checking license and storage") and rule 3
("do not download commercial/Sarvam models without official access")
govern every row.

**Execution note, stated once here rather than per-row**: this session's
dev sandbox is a Windows machine with no `ollama` binary installed and no
reachable connection to the actual robot hardware (`wise150@192.168.1.16`
did not respond to a reachability check this session — see
`docs/AI_MODEL_CURRENT_AUDIT.md`). Scripts in Phase 4 are written to run
correctly on the target (the Pi), and are **not executed against real
infrastructure by this pass** except where noted. `qwen2.5:0.5b`
specifically was already pulled and benchmarked on the real Pi-2 in an
earlier session pass (`docs/PI2_QWEN25_05B_SETUP_REPORT.md`, 2026-07-06)
— that download is not repeated or re-verified here.

## A. Local LLM

| Model | License | Commercial allowed | Size | Auto-download this pass? |
|---|---|---|---|---|
| `qwen2.5:0.5b` (primary) | Apache 2.0 (Qwen2.5 series, per Alibaba/Qwen's published model card) | Yes | ~397 MB (confirmed real pull size, `PI2_QWEN25_05B_SETUP_REPORT.md`) | **Already downloaded on real Pi-2 hardware, 2026-07-06.** Not re-downloaded this pass (no Ollama in this sandbox to re-verify against). |
| `llama3.2:1b` (benchmark-only) | Llama 3.2 Community License (Meta) — has field-of-use/attribution/acceptable-use conditions, not a plain permissive license | Yes, with conditions | ~1.3 GB | **No** — explicit instruction: benchmark-only candidate, requires explicit approval before downloading. Not approved this pass. |
| `qwen2.5:1.5b` (benchmark-only) | Apache 2.0 | Yes | ~986 MB | **No** — same rule: not approved this pass. |

## B. ASR

| Model | License | Commercial allowed | Size (approx) | Auto-download this pass? |
|---|---|---|---|---|
| Sarvam Edge ASR / Saaras v3 | Commercial, Sarvam AI proprietary | Requires Sarvam's own commercial terms | Unknown (no access to check) | **No — no official access detected in this environment (rule 3/12).** Zero prior integration found (Phase 1 audit). Not downloaded, not invented. |
| faster-whisper (already the repo's real choice) | MIT (faster-whisper wrapper) + the underlying Whisper model weights are MIT (OpenAI) | Yes | tiny≈75MB / base≈145MB / small≈484MB (per model size) | **Already the registered default in `pi2_requirements.txt`.** No new download needed — this pass registers it, doesn't re-fetch it. |
| sherpa-onnx ASR models (e.g. `sherpa-onnx-streaming-zipformer` multilingual) | Apache 2.0 (k2-fsa/sherpa-onnx project); individual model weights vary, most are Apache-2.0/CC-BY from the same project | Yes (verify per-model card at download time) | ~50-300 MB depending on model | **No, not this pass** — package (`sherpa-onnx` pip wheel) and model weights aren't present anywhere in the repo (GAP-7); registered as `enabled_by_default: false`, download command documented (`scripts/ai_models/install_sherpa_onnx.sh`) but not executed (no target Pi reachable). |
| whisper.cpp tiny/base (benchmark fallback) | MIT (ggerganov/whisper.cpp) + OpenAI Whisper weights (MIT) | Yes | tiny≈75MB / base≈142MB (ggml quantized) | **No, not this pass** — same reasoning as sherpa-onnx; script written, not executed. |

## C. TTS

| Model | License | Commercial allowed | Size (approx) | Auto-download this pass? |
|---|---|---|---|---|
| Sarvam Edge TTS / Bulbul v3 | Commercial, Sarvam proprietary | Requires official access | Unknown | **No — no official access detected.** |
| Piper `en_US-lessac-medium` (already the repo's choice) | MIT (Piper project) + individual voice models are CC0/MIT per the piper-voices model card | Yes | ~63 MB | **Already registered/expected installed** (`piper-tts` in `pi2_requirements.txt`) — not re-downloaded. |
| Piper Hindi voice (e.g. `hi_IN-*`) | Same Piper voice licensing (CC0/MIT, verify per-voice card) | Yes | ~60-100 MB | **No, not this pass** — GAP-8, registered as available/not-enabled, download command documented, not executed. |
| sherpa-onnx VITS TTS models | Apache 2.0 / model-card-dependent | Yes (verify per model) | ~20-100 MB | **No, not this pass.** |
| Indic TTS models (e.g. AI4Bharat) | Varies by model (many AI4Bharat releases are research/non-commercial or CC-BY-NC) | **Unknown/restricted for several** — must verify per-model before any use | Varies | **No — license status is `unknown` for several candidate Indic TTS releases; rule 2 blocks auto-download until verified per-model.** |

## D. Wake word / VAD

| Model | License | Commercial allowed | Size | Auto-download this pass? |
|---|---|---|---|---|
| Silero VAD (already the repo's real default) | MIT | Yes | ~2 MB (jit model) | Already the registered default (`torch.hub` fetch) — not re-downloaded. |
| openWakeWord (already real code, disabled by default) | Apache 2.0 | Yes | ~1-5 MB per wake-word ONNX model | Registered as available; not newly downloaded (already in the codebase's dependency surface, per Phase 1 audit). |
| Porcupine (optional) | **Commercial** (Picovoice) — free tier has usage limits, not unconditionally open | Free tier only, with limits | Small | **No** — licensing is conditional, not unconditionally open; registered as `commercial_allowed: unknown` pending an explicit decision, never auto-downloaded. |
| sherpa-onnx KWS models | Apache 2.0 | Yes | Small | **No, not this pass** — same as sherpa-onnx ASR, script written not executed. |

## E. Vision (object/person/pose)

| Model | License | Commercial allowed | Size | Auto-download this pass? |
|---|---|---|---|---|
| Hailo Model Zoo YOLO (object/person/pose `.hef`) | Hailo's Model Zoo license (mixed — many are Apache 2.0 upstream YOLO recompiled for Hailo, verify the specific model's license file in the Model Zoo repo) | Verify per model | 5-30 MB per compiled `.hef` | **No — HARDWARE_BLOCKED.** Requires a real AI HAT+2/Hailo device + Hailo Dataflow Compiler access to produce a `.hef`; neither exists in this environment (GAP-10). Not invented. |
| `ultralytics` YOLOv8n/YOLOv8s (CPU ONNX fallback) | AGPL-3.0 (Ultralytics' own license) **or** a paid Ultralytics Enterprise license for closed-source commercial use | **Conditional** — AGPL-3.0 requires the whole application to be open-sourced if distributed, unless an Enterprise license is purchased | ~6-22 MB (`.pt`), similar for exported `.onnx` | **Flagged, not newly downloaded.** The repo already depends on `ultralytics` (per `pi2_requirements.txt`, already in the real install manifest from an earlier pass) — this pass does not re-litigate that existing dependency decision, but the AGPL-3.0 term is recorded honestly in the registry (`commercial_allowed: unknown` pending a legal decision on BonBon's own distribution model) rather than silently marked "allowed." |

## F. Face recognition / emotion / diarization

| Model | License | Commercial allowed | Size | Auto-download this pass? |
|---|---|---|---|---|
| InsightFace (buffalo_l etc.) | **Non-commercial research license** on the pretrained model weights (InsightFace's own model zoo terms) — the code (BSD-ish) is separate from the weights' license | **No for commercial use of the pretrained weights** without separate licensing | ~250 MB | **No — flagged as license-restricted, not auto-downloaded regardless of "already in pi2_requirements.txt."** This is a real finding this plan surfaces: the existing dependency choice needs a legal review before production commercial use; registered in the new registry as `commercial_allowed: false` for the pretrained weights specifically (the `insightface` *package* itself is open, the *weights* are the restricted part). |
| DeepFace (emotion + face recognition backends) | MIT (DeepFace wrapper); underlying models vary (e.g. Facenet512 weights are MIT/BSD-derivative, VGG-Face has its own academic-use terms) | Mostly yes, verify per underlying model | ~90-500 MB depending on backend model | Not newly downloaded this pass (GAP-1 already covers the install-manifest gap) — license recorded per sub-model. |
| SpeechBrain `emotion-recognition-wav2vec2-IEMOCAP` | Apache 2.0 (SpeechBrain) — underlying wav2vec2 base is MIT (Facebook/Meta) | Yes | ~1.2 GB | Not newly downloaded this pass (GAP-1) — license clean, size is the real constraint worth flagging for a 4-core Pi-2 with LLM/vision also competing for RAM. |
| pyannote `speaker-diarization-3.1` | **Gated on Hugging Face — requires accepting the model's own terms + a personal HF access token**, not a simple open download | Commercial use requires reading pyannote's specific terms (historically restrictive for commercial diarization use without a paid plan) | ~150 MB | **No — gated + license status genuinely unclear for commercial use; already correctly disabled by default in the real code (`enabled=False`).** This pass does not change that default. |

## Storage budget check (informational, not enforced against a real device this pass)

Sum of everything **already** expected-installed per `pi2_requirements.txt`
(torch/torchaudio/transformers/mediapipe/ultralytics/insightface/chromadb/
faster-whisper's own model cache/etc.) plausibly exceeds 3-4 GB of
Python packages alone before any model weights are counted — a real
concern on a Pi 5 with finite SD/NVMe storage. `scripts/ai_models/precheck_models.py`
(Phase 4) checks available storage before printing any download plan;
this document does not claim a specific free-space number for the real
Pi-2 since this session has no live connection to read it (last known
figure: `PI2_HARDWARE_CHECK_REPORT.md` did not record disk space, only
temperature/throttling).

## What this pass will actually fetch, right now, in this environment

**Nothing.** This dev sandbox has no Ollama, no reachable Pi, and
installing Python ML packages (torch, mediapipe, etc.) into this
Windows sandbox would not help the actual Raspberry Pi deployment and
risks polluting an unrelated environment. Every "download" in this pass
is: (a) a correctly-written, not-yet-executed script (Phase 4), or (b)
an already-completed prior download this pass merely registers
(`qwen2.5:0.5b`, already on Pi-2). This is the honest, rule-2/rule-1-compliant
answer, not a gap to apologize for.
