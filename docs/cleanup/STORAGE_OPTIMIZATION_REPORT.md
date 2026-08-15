# Storage Optimization Report

**Phase 6.** Builds directly on `DISK_USAGE_REPORT.md` (Phase 1) and the dead-asset findings from Phase 4. Total repository footprint on disk in this environment: **2.5G**. This report separates what's real git/deployment weight from what's local-only regenerable cache, and quantifies what a safe cleanup actually saves.

## The honest headline: ~97% of this repo's on-disk size is not a "repo size" problem at all

| Category | Size | Git-tracked? | Regenerable? |
|---|---|---|---|
| `.venv/` | 1.6G | No | Yes (`pip install`) |
| `ros2_ws/src/bonbon_operator_api/frontend/{node_modules,dist}/` | ~571M | No | Yes (`npm install` / `npm run build`) |
| `ros2_ws/src/bonbon_patient_kiosk/frontend/node_modules/` | ~75M | No | Yes (`npm install`) |
| `.git/` (real history + LFS objects) | 136M | N/A — this IS the repo | No (this is the actual repo) |
| `ros2_ws/build/`, `install/`, `log/` | ~41M | No | Yes, but stale (generated on a different machine; this environment can't regenerate — no colcon installed) |
| `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/` (+ hundreds of per-package copies) | ~16M+ | No | Yes |
| `models/` (real production TTS model) | 61M | Yes, LFS | No — this is real content |
| Everything else (`docs/`, `tests/`, `config/`, all 44 packages' source) | ~15M | Yes | No — this is the actual codebase |

**Real, permanent git-repo weight (excluding LFS): roughly 15-20M of source + docs.** The `.git/` directory's 136M is mostly LFS-object storage for legitimate binary assets (models, WASM runtimes, audio samples) — not bloat, just what those assets actually cost.

## Actionable local-disk savings (Phase 11 candidates, zero git impact)

| Action | Saves | Risk |
|---|---|---|
| Remove `.venv/` | 1.6G | None — recreate with `pip install -r requirements/pi2_requirements.txt` (or project's real dev-setup command) |
| Remove `bonbon_operator_api/frontend/{node_modules,dist}` | ~571M | None — `npm install` + `npm run build` regenerate both; production Docker build never uses the local copy |
| Remove `bonbon_patient_kiosk/frontend/node_modules` | ~75M | None — same reasoning |
| Remove `ros2_ws/{build,install,log}` | ~41M | None — gitignored, and this environment has no way to regenerate via colcon anyway, so the stale copies have zero value |
| Remove `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/` (root + all per-package) | ~16M+ | None — regenerate on next tool run automatically |

**Total local-disk reclaim if all of the above are cleared: ~2.3G of this environment's 2.5G total**, none of it touching a single git-tracked byte. This is the single largest, safest, and least interesting-sounding finding of the whole storage audit — most of what looks like "repo bloat" here is just an uncleaned local dev environment, not something wrong with the repository itself.

## Actionable git-repo savings (smaller in bytes, but these are the ones that matter for repo/clone size)

| Action | Saves (real, git-tracked) | Evidence |
|---|---|---|
| Remove `bonbon_perception/` (dead duplicate, Phase 3) | 739K | Confirmed dead — see `DUPLICATE_PIPELINE_REPORT.md` |
| Remove `frontend/public/models/hands/*` (9 files, 3 LFS-tracked) | ~15M (mostly LFS: `hand_landmark_full.tflite` 5.5M + `hands_solution_simd_wasm_bin.wasm` 6.0M + smaller files) | Confirmed dead asset bundle — see `STALE_MOCK_AND_PLACEHOLDER_REPORT.md` |
| Remove `deploy/pi2_deployment_bundle.tar.gz` | 667K local only (already gitignored, not a git-size item) | Confirmed local-only artifact |
| Relocate (not delete) `deploy/{pi2_manifest.txt,pi2_exclude.txt,pi2_qwen_benchmark_results.json}` to `docs/archive/` | 0 (relocation, not size reduction) | Preserves historical value per `DELETE_RISK_REGISTER.md` |
| Remove unused Python/npm deps (`torchaudio`, `python-multipart`, `@mediapipe/hands`, `@tensorflow-models/hand-pose-detection`) | 0 direct repo bytes (these are dependency *declarations*, not vendored code — the size saving happens in each environment's own `.venv`/`node_modules` at install time, not in git) | See `UNUSED_DEPENDENCY_REPORT.md` |

## What's explicitly NOT a storage problem (checked, ruled out)

- All 12 Git LFS-tracked assets (minus the 3 in the dead `hands/` bundle above) are real, actively-referenced, non-duplicated production files.
- `models/piper/en_US-lessac-medium.onnx` (61M) — the single largest tracked file in the repo, and it's exactly what it should be: the one TTS voice model this robot actually uses.
- No duplicate model formats found (e.g. no `.onnx` AND `.tflite` copies of the same model).
- `docs/` (2.0M across ~150 files) and `tests/` (2.2M) are proportionate to a project of this scope — not flagged for reduction.
