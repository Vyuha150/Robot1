# Unused Dependency Report

**Phase 4** (feeds Phase 7 for the final removal). Every dependency in `pyproject.toml`, `requirements/pi2_requirements.txt`, and `ros2_ws/src/bonbon_operator_api/frontend/package.json` was checked against real `import`/usage statements in source. `founder_command_center/backend/requirements.txt` was left unanalyzed per the user's decision to leave that directory untouched entirely.

## `pyproject.toml` (root)

No `[project.dependencies]` table exists — this file is tooling config only (black/ruff/mypy/coverage settings). Nothing to audit.

## `requirements/pi2_requirements.txt`

| Package | Status | Evidence |
|---|---|---|
| `torchaudio` | **REMOVE** | Zero `import torchaudio` hits anywhere in `ros2_ws/src`, `scripts`, `tests`, `devops`. Only appearance in the whole repo is the requirements line itself. `torch` proper IS used (lazy-imported in `bonbon_speech/vad/silero_vad.py` and `bonbon_speech/diarization/pyannote_diarizer.py`) — this is specifically about the separate `torchaudio` package. |
| `python-multipart` | **REMOVE** | No `Form(`, no `: UploadFile`, no multipart form parsing anywhere in the FastAPI backends. This dashboard doesn't parse multipart bodies or handle file uploads. |
| `numba`, `nvidia-ml-py` | KEEP — documented transitive pin | Zero direct imports, but the file's own header comments explain these exist specifically to stop pip's resolver from pulling in the NVIDIA CUDA toolkit on a CPU-only Pi target. Removing them would risk reintroducing that problem. |
| `ultralytics` | KEEP | Used by live `bonbon_vision/detectors/yolo_detector.py`. (Also referenced by the now-dead `bonbon_perception/detectors/yolo_person_detector.py`, but `bonbon_vision` alone justifies keeping it.) |
| Everything else (`insightface`, `onnxruntime`, `faster-whisper`, `torch`, `sounddevice`, `mediapipe`, `transformers`, `sentence-transformers`, `deepface`, `speechbrain`, `ollama`, `langchain`, `langchain-community`, `chromadb`, `piper-tts`, `fastapi`, `uvicorn`, `PyJWT`, `passlib`, `prometheus-client`, `httpx`) | KEEP | Each has ≥1 genuine import match in source |

## `ros2_ws/src/bonbon_operator_api/frontend/package.json`

| Package | Status | Evidence |
|---|---|---|
| `@mediapipe/hands` | **REMOVE** | Zero references in `frontend/src` |
| `@tensorflow-models/hand-pose-detection` | **REMOVE** | Zero references in `frontend/src` |
| `@mediapipe/tasks-vision`, `@tensorflow-models/coco-ssd`, `@tensorflow/tfjs`, `@vladmandic/face-api` | KEEP | Each has ≥1 real usage in `src` |

**These two unused npm packages correlate exactly with the dead `public/models/hands/*` asset bundle** (see `STALE_MOCK_AND_PLACEHOLDER_REPORT.md`) — both are remnants of an older hand-tracking implementation superseded by the MediaPipe Gesture Recognizer task (`@mediapipe/tasks-vision`, actively used at `frontend/src/App.tsx:2427`). Remove the npm packages and the asset bundle together, not separately — they're one coherent piece of dead functionality.

## Combined removal list for Phase 7/11

```
requirements/pi2_requirements.txt:  remove torchaudio, python-multipart
frontend/package.json:              remove @mediapipe/hands, @tensorflow-models/hand-pose-detection
frontend/public/models/hands/*:     remove 9 files (see STALE_MOCK_AND_PLACEHOLDER_REPORT.md)
```

None of these removals touch anything safety-critical, hardware-gated, or currently in active use — all four are confirmed-dead by negative grep evidence, not inference.
