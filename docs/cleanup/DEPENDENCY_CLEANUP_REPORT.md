# Dependency Cleanup Report

**Phase 7.** Consolidates and finalizes the dependency findings from Phase 4 (`UNUSED_DEPENDENCY_REPORT.md`), cross-checked against `requirements/pi2_requirements.txt`'s own extensive in-file documentation.

## Confirmed removals (unchanged from Phase 4, re-verified against the requirements file's rationale)

| Package | File | Status | Why this is safe |
|---|---|---|---|
| `torchaudio` | `requirements/pi2_requirements.txt:112` | **REMOVE** | Zero imports anywhere in the repo. Unlike every other real dependency in this file, it has **no explanatory comment** justifying its inclusion — every genuinely-needed package here (torch, faster-whisper, deepface, speechbrain, mediapipe, etc.) has a paragraph explaining why it's needed and what tradeoff was made. `torchaudio`'s silence, combined with zero usage, strongly indicates it was added defensively alongside `torch` and never actually needed. |
| `python-multipart` | `requirements/pi2_requirements.txt:156` | **REMOVE** | Same pattern — grouped under "Operator dashboard API" with no rationale comment, and zero multipart-form/file-upload code exists anywhere in `bonbon_operator_api` or `bonbon_patient_kiosk`. |
| `@mediapipe/hands` | `frontend/package.json` | **REMOVE** | Zero references; dead alongside its asset bundle (`STALE_MOCK_AND_PLACEHOLDER_REPORT.md`) |
| `@tensorflow-models/hand-pose-detection` | `frontend/package.json` | **REMOVE** | Same — dead alongside the same asset bundle |

## Explicitly KEPT despite zero direct imports — these are real, documented Pi-compatibility decisions, not dead weight

`requirements/pi2_requirements.txt` already contains unusually thorough Pi-compatibility engineering, verified genuine (not just claimed) by cross-referencing each rationale against real build behavior described in the comments:

- **`numba<0.59`, `nvidia-ml-py==12.560.30`** — zero direct imports (both are transitive), but the file explains exactly why: without these pins, pip's resolver backtracks into the full NVIDIA CUDA toolkit metapackage trying to satisfy a numba/cuda-bindings requirement pulled in transitively (documented as reproduced on a real build: "sat backtracking... for over 40 minutes before being killed"). Removing these pins would not just be neutral — it would actively reintroduce a multi-gigabyte, GPU-useless dependency pull on a Raspberry Pi 5 with no NVIDIA silicon.
- **`faster-whisper` over `openai-whisper`** — the file documents a real, tested reason: `openai-whisper` hard-depends on `triton` (NVIDIA GPU-kernel compilation), reproducing the same CUDA-toolkit pull problem, confirmed on a real build attempt.
- **`deepface` and `speechbrain` present, despite `deepface` being excluded elsewhere for face recognition** — the file correctly distinguishes deepface's two different uses in this codebase (face recognition, where it's redundant with insightface and excluded; emotion analysis in `bonbon_affective_ai`, where it's the actual code default and needed). This is careful, not careless.
- **`pyannote.audio` intentionally absent** — documented protobuf version conflict with `mediapipe` (verified against real wheel metadata per the comment), and diarization is disabled by default anyway (`bonbon_speech/launch/speech.launch.py`'s `diarization_enabled` defaults to false) — dropping it has zero effect on anything currently reachable.
- **`mediapipe`'s aarch64 wheel availability** — honestly flagged in-file as a real installation risk, "not assumed to just work" — exactly the kind of honest-uncertainty flagging this whole cleanup audit values.

**None of these are cleanup targets.** They represent real engineering work already done to keep this deployment Pi-compatible; re-flagging them as "unused" without reading the rationale would be exactly the kind of guessing this audit's own rules forbid.

## Root `pyproject.toml`

No `[project.dependencies]` table — tooling config only (black/ruff/mypy/coverage). Nothing to clean up here.

## `founder_command_center/backend/requirements.txt`

Left unanalyzed — this directory is explicitly out of scope for the entire cleanup per the user's decision (see `DELETE_RISK_REGISTER.md`).
