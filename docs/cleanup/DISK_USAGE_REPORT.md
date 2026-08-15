# Disk Usage Report (Baseline)

**Status: COMPLETE.** Full recursive `du -h --max-depth=3 .` finished (`disk_usage_before.txt`, 208 lines) plus a fast single-pass large-file scan (`large_files_2mb_plus.txt`) scoped to exclude already-characterized regenerable directories.

## Total repository size: 2.5G on disk (this environment)

## Top contributors (from full `du -h --max-depth=3`)

| Path | Size | Git-tracked? |
|---|---|---|
| `.venv/` | **1.6G** | No (gitignored local virtualenv) |
| `ros2_ws/src/bonbon_operator_api/` | **572M** | Partially — see breakdown below |
| `.git/` | 136M | N/A (repo history + LFS objects, 22M pack + 114M LFS) |
| `ros2_ws/src/bonbon_patient_kiosk/` | 75M | Yes (need same node_modules/dist check as operator_api — not yet done, Phase 6 follow-up) |
| `models/` | 61M | Yes, LFS |
| `ros2_ws/build/` | 35M | No (gitignored, stale colcon artifact) |
| `.mypy_cache/` | 14M | No (gitignored) |
| `ros2_ws/install/` | 3.8M | No (gitignored) |
| `ros2_ws/log/` | 2.0M | No (gitignored) |
| `.ruff_cache/` | 2.0M | No (gitignored) |
| `docs/` | 2.0M | Yes |
| `tests/` | 2.2M | Yes |

**`ros2_ws/src/bonbon_operator_api`'s 572M is fully explained and is NOT a real repo-size problem**: it hosts a full React/TypeScript dashboard frontend at `frontend/`, and `frontend/node_modules/` + `frontend/dist/` are both confirmed gitignored (`frontend/.gitignore` lines 1-2) — standard npm dependency cache and Vite build output, both fully regenerable (`npm install`, `npm run build`) and confirmed NOT referenced by the production Docker build (`deployment/docker/Dockerfile.dashboard-web` runs its own multi-stage `npm run build` inside the image, never copies this local `dist/`). Zero git impact, zero deployment impact — pure local disk usage, same category as `.venv`.

## Large files (>2MB), excluding `.venv`/`.git`/`node_modules`/`ros2_ws/build|install|log`

```
63.2M  models/piper/en_US-lessac-medium.onnx                                        (real, LFS, production TTS model)
11.2M  frontend/public/models/gesture/wasm/vision_wasm_module_internal.wasm         (LFS, real — MediaPipe gesture runtime)
11.2M  frontend/dist/models/gesture/wasm/vision_wasm_module_internal.wasm           (identical byte-for-byte copy in gitignored build output)
11.2M  frontend/public/models/gesture/wasm/vision_wasm_internal.wasm                (LFS, real)
11.2M  frontend/dist/models/gesture/wasm/vision_wasm_internal.wasm                  (build-output duplicate)
10.5M  frontend/public/models/gesture/wasm/vision_wasm_nosimd_internal.wasm         (LFS, real)
10.5M  frontend/dist/models/gesture/wasm/vision_wasm_nosimd_internal.wasm           (build-output duplicate)
8.4M   frontend/public/models/gesture/gesture_recognizer.task                       (LFS, real)
8.4M   frontend/dist/models/gesture/gesture_recognizer.task                         (build-output duplicate)
6.0M   frontend/public/models/hands/hands_solution_simd_wasm_bin.wasm               (LFS, real)
6.0M   frontend/dist/models/hands/hands_solution_simd_wasm_bin.wasm                 (build-output duplicate)
5.5M   frontend/public/models/hands/hand_landmark_full.tflite                       (LFS, real)
5.5M   frontend/dist/models/hands/hand_landmark_full.tflite                         (build-output duplicate)
4.3M   frontend/public/models/hands/hands_solution_packed_assets.data               (LFS, real)
4.3M   frontend/dist/models/hands/hands_solution_packed_assets.data                 (build-output duplicate)
2.6M   .mypy_cache/3.11/cache.4.db                                                   (gitignored cache DB)
2.1M   .mypy_cache/3.11/cache.3.db                                                   (gitignored cache DB)
```

**Every "duplicate" here is the exact same LFS-tracked model file appearing once in `frontend/public/` (the real, git-tracked source Vite copies from) and once in `frontend/dist/` (the gitignored build output)** — this is expected, correct Vite behavior, not accidental duplication. No new large-file waste found beyond what's already explained above.

## Confirmed directory sizes (non-recursive `du -sh`, timeout-bounded)

| Directory | Size | Notes |
|---|---|---|
| `models/` | 61M | 2 files: `piper/en_US-lessac-medium.onnx` (the bulk of this) + its `.json` config. Real, LFS-tracked, production TTS model. |
| `tests/` | 2.2M | Top-level cross-package test suite source (1013 tests as of prior session). |
| `docs/` | 2.0M | ~150+ markdown files accumulated over this project's iterative development. |
| `deploy/` | 709K | One-off Pi-2 deployment artifact bundle (`pi2_deployment_bundle.tar.gz` 667K + manifest/exclude/benchmark files). |
| `deployment/` | 320K | Deployment engineering tree (compose/docker/systemd/security/monitoring/ota/scripts) — config only, no large binaries. |
| `samples/` | 304K | 2 WAV files, ASR test audio. LFS-tracked. |
| `founder_command_center/` | 196K | Separate app; purpose relative to BonBon not yet confirmed (Phase 2). |

**Not yet measured (background scan slow/incomplete):** `.venv/`, `ros2_ws/` (src+build+install+log combined), `Bonbon-robot/`, `config/`, `scripts/`, `devops/`, `bonbon_behavior_validation/`, `bonbon_field_learning/`, `launch/`.

## File-count-based signals (faster than `du`, equally useful for cleanup targeting)

| Location | File count | Git-tracked? | Notes |
|---|---|---|---|
| `.venv/` | 10,760 | **No** (gitignored, confirmed via `git check-ignore`) | Local Python virtualenv. Zero impact on repo/git size. Real local disk usage only. |
| `ros2_ws/build/` | 2,178 | **No** (gitignored) | colcon build artifacts, dated May 26 — predates this session, generated on a different/earlier environment (this sandbox has no colcon installed now). |
| `ros2_ws/install/` | 158 | **No** (gitignored) | colcon install artifacts, same generation event as `build/`. |
| `ros2_ws/log/` | 85 | **No** (gitignored) | colcon build logs, same generation event. |
| `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/` (root) | not counted individually | **No** (all show `!!` = ignored in `git status --ignored=matching`) | Tool caches from this session's own lint/type/test runs. |
| Per-package `__pycache__/` and `.pytest_cache/` | hundreds, one set per `ros2_ws/src/*/` package + `tests/`, `scripts/`, `bonbon_behavior_validation/`, `bonbon_field_learning/`, `devops/`, `launch/edge_ai/` | **No** (all confirmed ignored) | Standard Python bytecode caches. |
| `Bonbon-robot/` | 0 (only a `.git/` dir, 0 commits) | N/A (nested repo, invisible to outer repo's git) | See finding in `CLEANUP_BASELINE_REPORT.md` — empty, uninitialized nested git repo. |

## Git LFS-tracked binary assets (12 files, all confirmed real)

```
models/piper/en_US-lessac-medium.onnx                                              (TTS voice model)
samples/asr/doctor_room_entity.wav                                                 (ASR test sample)
samples/asr/en_hospital_phrase.wav                                                 (ASR test sample)
ros2_ws/src/bonbon_operator_api/frontend/public/models/face/face_expression_model.bin
ros2_ws/src/bonbon_operator_api/frontend/public/models/face/tiny_face_detector_model.bin
ros2_ws/src/bonbon_operator_api/frontend/public/models/gesture/gesture_recognizer.task
ros2_ws/src/bonbon_operator_api/frontend/public/models/gesture/wasm/vision_wasm_internal.wasm
ros2_ws/src/bonbon_operator_api/frontend/public/models/gesture/wasm/vision_wasm_module_internal.wasm
ros2_ws/src/bonbon_operator_api/frontend/public/models/gesture/wasm/vision_wasm_nosimd_internal.wasm
ros2_ws/src/bonbon_operator_api/frontend/public/models/hands/hand_landmark_full.tflite
ros2_ws/src/bonbon_operator_api/frontend/public/models/hands/hand_landmark_lite.tflite
ros2_ws/src/bonbon_operator_api/frontend/public/models/hands/hands_solution_simd_wasm_bin.wasm
```

All 12 are client-side dashboard/kiosk MediaPipe models (face/gesture/hand) plus the one server-side Piper TTS model and 2 ASR test samples — no duplicate model formats or obviously-unused binaries found in this pass. Confirmed via `git lfs ls-files`; a prior-session commit (`f3b3df2`, "Set up Git LFS for model/audio/binary artifacts") already did the work of moving these out of plain git blobs. This area looks clean already — no action expected here in Phase 6 beyond re-confirming nothing new has landed outside LFS since.

## Preliminary Phase 6 candidates (from this baseline alone, to be re-verified with evidence in Phase 6 itself)

1. `ros2_ws/build/`, `ros2_ws/install/`, `ros2_ws/log/` — gitignored, regenerable, stale (predates current source and this environment's lack of colcon) → likely `REMOVE_CACHE`.
2. Root `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/` + all per-package `__pycache__/`/`.pytest_cache/` → `REMOVE_CACHE`, standard and safe.
3. `Bonbon-robot/` — empty nested repo, zero content → likely `REMOVE_DEAD`, pending Phase 2 confirmation it isn't referenced anywhere (e.g. as a git submodule declaration, which was not found in `.gitmodules` — this repo has no `.gitmodules` file at all, confirmed absent).
4. `deploy/pi2_deployment_bundle.tar.gz` (667K) — a one-off deployment artifact from an already-completed Pi-2 deployment session. Whether it's still needed as a reference/rollback artifact or safe to remove is a judgment call for Phase 6/10, not decided here.

None of the above are acted on in this phase.
