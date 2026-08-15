# Restore Plan

**Phase 10 companion to `QUARANTINE_REPORT.md`.** Exact restore procedure for every item Phase 11 quarantines, should any of them turn out to be needed after all.

## Quarantine directory structure

```
_archive/quarantine_cleanup_20260814/
├── bonbon_perception/              # full package, moved intact
├── models_hands/                   # 9 files from frontend/public/models/hands/
│   ├── hands.binarypb
│   ├── hands.js
│   ├── hands_solution_packed_assets.data
│   ├── hands_solution_packed_assets_loader.js
│   ├── hands_solution_simd_wasm_bin.data
│   ├── hands_solution_simd_wasm_bin.js
│   ├── hands_solution_simd_wasm_bin.wasm
│   ├── hand_landmark_full.tflite
│   └── hand_landmark_lite.tflite
├── authority_manager.launch.py     # from bonbon_authority_manager/launch/
├── distributed_safety.launch.py    # from bonbon_distributed_safety/launch/
└── MANIFEST.md                     # this quarantine's own index, generated in Phase 11
```

## Restore commands, per item

| Item | Restore command |
|---|---|
| `bonbon_perception` | `git mv _archive/quarantine_cleanup_20260814/bonbon_perception ros2_ws/src/bonbon_perception` |
| Hand-tracking assets | `git mv _archive/quarantine_cleanup_20260814/models_hands/* ros2_ws/src/bonbon_operator_api/frontend/public/models/hands/` (recreate the `hands/` directory first if needed) |
| `authority_manager.launch.py` | `git mv _archive/quarantine_cleanup_20260814/authority_manager.launch.py ros2_ws/src/bonbon_authority_manager/launch/authority_manager.launch.py` |
| `distributed_safety.launch.py` | `git mv _archive/quarantine_cleanup_20260814/distributed_safety.launch.py ros2_ws/src/bonbon_distributed_safety/launch/distributed_safety.launch.py` |

Restoring the two npm packages (`@mediapipe/hands`, `@tensorflow-models/hand-pose-detection`) alongside the hand-tracking assets requires re-adding them to `ros2_ws/src/bonbon_operator_api/frontend/package.json`'s dependencies and running `npm install` — they aren't quarantined as files (dependency *declarations* aren't moved, just deleted from the manifest in Phase 11), so their restoration is a one-line `package.json` edit, not a `git mv`.

## Full-repository restore (if the entire Phase 11 execution needs to be undone)

Since this whole cleanup was performed on a dedicated branch (`cleanup/audit-2026-08-14`, created before any changes in Phase 1), the simplest total-rollback path is:

```bash
git checkout main   # or whichever branch you were on before this cleanup
git branch -D cleanup/audit-2026-08-14   # only if you're certain none of it should be kept
```

This is a last-resort option — even Tier 3 items (see `QUARANTINE_REPORT.md`) are never touched by this cleanup, so a full rollback only matters if you decide even the Tier 1/2 deletions (caches, `bonbon_perception`, dead assets) and the Phase 9 dashboard-truthfulness fixes should be discarded. Given the fixes in `DASHBOARD_FIX_REPORT.md` are real bug fixes with their own tests, discarding them would mean reintroducing the fake-success bugs — recommend reviewing the branch's commit history to selectively revert rather than discarding it wholesale.

## Verification after any restore

Whichever item is restored, re-run its package's test suite before considering the restore complete:

```bash
python -m pytest ros2_ws/src/<package>/tests/ -q
```

For `bonbon_perception` specifically, since it was already fully disabled before this cleanup (launch file `.disabled`, empty `console_scripts`), restoring it returns the repo to that same disabled-but-present state — it does not become live again without additional work to re-enable its launch file and console script entry.
