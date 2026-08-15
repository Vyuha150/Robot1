# Stale Mock and Placeholder Report

**Phase 4.** Searched for hardcoded fake data, dangling TODOs, and debug leftovers in production (non-test) code paths. Documented `Mock*` classes (`MockDetector`, `MockRuntime`, etc. — legitimate, intentional fallback implementations used throughout this codebase's fail-open design) were explicitly excluded from this search; this report is about accidental staleness, not designed mock fallbacks.

## Result: no stale mock/placeholder data found in production code

- `grep -rniE "TODO|FIXME|XXX|HACK"` across all non-test `.py` in `ros2_ws/src`, `scripts`, `devops` → **0 hits**.
- `grep -rn "console.log|debugger;"` in `frontend/src` → **0 hits**.
- Every "hardcoded" comment hit (25 files) was individually verified as either negative-space documentation ("X is NEVER hardcoded, injected via config") or a past-tense fix note describing something already corrected — e.g. `ros2_bridge.py:205`'s comment references "the previous hardcoded `success: True`, which actively lied," and the current code at lines 878-912 genuinely publishes a real ROS2 message and returns a status derived from that publish, not a leftover mock.
- `ai_model_status_api.py:1-14` explicitly documents its endpoints are backed by live `bonbon_ai_model_registry` snapshots, not static data — verified true.

This is a genuinely clean result, not an under-searched one — the negative greps above are real evidence of absence, not an assumption.

## Dead assets found (a different category — real files, not fake data)

### `frontend/public/models/hands/*` — 9 files, abandoned hand-tracking implementation

```
hands.binarypb
hands.js
hands_solution_packed_assets.data
hands_solution_packed_assets_loader.js
hands_solution_simd_wasm_bin.data
hands_solution_simd_wasm_bin.js
hands_solution_simd_wasm_bin.wasm    (Git LFS-tracked)
hand_landmark_full.tflite            (Git LFS-tracked)
hand_landmark_lite.tflite            (Git LFS-tracked)
```

Zero references anywhere in `frontend/src` (`grep -rn "models/hands|@mediapipe/hands|hand_landmark|hands_solution" src` → 0 hits). This is the asset counterpart to the two unused npm packages found in `UNUSED_DEPENDENCY_REPORT.md` (`@mediapipe/hands`, `@tensorflow-models/hand-pose-detection`) — the same abandoned hand-tracking pipeline, since replaced by the MediaPipe Gesture Recognizer task (`@mediapipe/tasks-vision`, actively used). **Classification: REMOVE**, as one coherent unit alongside the npm packages, not separately. 3 of these 9 files are Git LFS-tracked, so this removal reduces real repo storage, not just local disk (see `STORAGE_OPTIMIZATION_REPORT.md`, Phase 6).

## Docs needing a quarantine caveat (not deletion — content is otherwise accurate)

- **`docs/modules.md:113-132`** — section `## bonbon_perception and bonbon_vision` describes `bonbon_perception` as a co-equal active module. It's actually fully quarantined (see `ros2_ws/src/bonbon_perception/README.md:1`, `docs/KNOWN_LIMITATIONS.md:30`). **QUARANTINE**: needs the same quarantine caveat other docs already correctly carry, not a rewrite of the `bonbon_vision` content, which remains accurate.
- **`docs/overview.md:20`** — lists `bonbon_perception, bonbon_vision, bonbon_perception_ai` together with no annotation distinguishing the dead one. **QUARANTINE**: add a note or drop the name.

11 other docs matched a broader "deprecated|superseded|no longer used" grep, but on inspection all correctly and currently describe `bonbon_perception`'s quarantine status already (`docs/EDGE_AI_GAP_ANALYSIS.md`, `docs/EDGE_AI_RUNTIME_FINAL_REPORT.md`, `docs/PI2_DEPLOYMENT_FILE_AUDIT.md`, `docs/REPOSITORY_VERIFICATION_REPORT.md`, `docs/ARCHITECTURE_FREEZE.md`, and others) — these are accurate, not obsolete. KEEP, no action.
