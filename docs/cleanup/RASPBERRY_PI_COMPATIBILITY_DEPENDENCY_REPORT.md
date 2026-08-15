# Raspberry Pi Compatibility Dependency Report

**Phase 7.** Assesses whether this repo's dependencies are actually suitable for its real deployment target (Raspberry Pi 5, ARM64, no NVIDIA GPU) rather than just "installed successfully in some environment."

## Overall finding: this repo's Pi compatibility posture is already strong

`requirements/pi2_requirements.txt` is not a generic pip-freeze — it's a hand-curated, heavily-commented manifest where nearly every non-obvious inclusion or exclusion decision is documented with the *reason*, often citing a real build failure that was reproduced and fixed. This is uncommon rigor and should be preserved, not "cleaned up" by someone unfamiliar with why each pin exists.

## x86/CUDA-only risk: actively defended against, not present

| Risk | How it's handled |
|---|---|
| PyTorch pulling the full NVIDIA CUDA toolkit | CPU-only wheel index set globally in `deployment/docker/Dockerfile.ai`'s pip install command, not per-line (the file's own comment explains why a per-line override isn't sufficient — pip's resolver can still backtrack into a CUDA build via a transitive dependency like `mediapipe` or `sentence-transformers`) |
| `numba`'s transitive `cuda-bindings` requirement on newer releases | Pinned `numba<0.59`, reproduced and documented (40+ minute resolver hang before the fix) |
| `openai-whisper`'s hard dependency on `triton` (NVIDIA GPU-kernel compiler) | Deliberately not installed; `faster-whisper` (CTranslate2, CPU-optimized) used instead — also faster on this hardware, not just safer |
| `nvidia-ml-py` version drift during resolver backtracking | Pinned to a single exact version; the package itself is a harmless no-op GPU-query binding on hardware with no GPU |

## ARM64 wheel availability: honestly flagged, not assumed

`mediapipe` (the real backend for `bonbon_gesture`) is flagged in-file as having "historically had incomplete/lagging aarch64 Linux wheel availability" — documented as a genuine, reportable risk rather than silently assumed to work. This audit did not independently re-verify current wheel availability (would require a real network check against PyPI for the exact Python/ARM64 combination used on the actual Pi 5 hardware, which this dev sandbox cannot do) — carrying the existing honest flag forward rather than either dismissing or fabricating a resolution.

## Heavy packages used only once — reviewed, all justified

- **`speechbrain`** (~1.2GB with wav2vec2 base weights) — used once, in `bonbon_affective_ai` for voice emotion recognition. The requirements file itself flags this as a real RAM-budget concern on a Pi-2 already running LLM+vision+ASR concurrently, explicitly deferring the "should we ship this" resource-tradeoff decision to "the resource-policy/Pi-efficiency-profile owner" rather than silently absorbing it. This audit is not the place to make that resource-budget call either — noted, not resolved here.
- **`chromadb`** — used once (RAG vector store default backend), justified by `bonbon_llm`'s config default; the lighter alternative (`faiss-cpu`) is correctly left uninstalled since it's not the active backend.
- **`ultralytics`** (YOLO) — used once in `bonbon_vision`'s live detector — real, necessary, not overkill for the job it does (person/object detection is the core sensing capability this robot needs).

None of these are flagged as removal candidates — "used once" is not itself a problem when the one use is real and necessary; it would only be a concern if the single user turned out to be dead code, which none of these are (all confirmed live in `FILE_CLASSIFICATION_MATRIX.md`).

## Deliberately-excluded packages — confirmed correct, not oversights

- **`pyannote.audio`** — real protobuf version conflict with `mediapipe` (verified against actual wheel metadata per the in-file comment), and the feature it enables (speaker diarization) is disabled by default anyway. Re-including it would either break the build or require running two separate Python environments — not worth it for a disabled-by-default feature.
- **`deepface`** — correctly excluded for face *recognition* (redundant with `insightface`) but correctly *included* for emotion analysis in `bonbon_affective_ai`, where it's the actual code default. This nuance is right, not a mistake.
- **`faiss-cpu`** — correctly excluded since `chromadb` is the active RAG backend.

## Recommendation

**No new Pi-compatibility issues found.** The only two dependency-cleanup actions from this phase (`torchaudio`, `python-multipart` removal — see `DEPENDENCY_CLEANUP_REPORT.md`) are unrelated to Pi-compatibility; they're simply unused. Everything Pi-specific in this requirements file should be left exactly as-is — it represents real, hard-won engineering knowledge about this specific deployment target, encoded directly in comments where a future maintainer (or a less careful cleanup pass) can see and respect it.
