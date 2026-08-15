# Cleanup Execution Log

**Phase 11.** Chronological record of every action actually taken, in the brief's prescribed safe order. Full regression results are in `POST_CLEANUP_TEST_REPORT.md` (Phase 12) — this log records what was done and the per-step spot-checks run at the time.

## 1. Remove generated caches

| Action | Result |
|---|---|
| `rm -rf .mypy_cache .ruff_cache` | Removed cleanly |
| `rm -rf .pytest_cache` | **Blocked** — OS-level permission denial, same issue documented in Phase 1's baseline (`CURRENT_BUILD_TEST_BASELINE.md`). Not forced through; left in place. |

## 2. Remove old logs/build outputs

| Action | Result |
|---|---|
| `rm -rf ros2_ws/build ros2_ws/install ros2_ws/log` | Removed cleanly — confirmed gitignored, confirmed stale (no colcon in this environment to have produced them recently) |
| `rm -rf .venv` | Removed cleanly — confirmed this session's own commands use system Python (`sys.prefix` checked directly), not this virtualenv, so nothing in this session was broken |
| `rm -rf bonbon_operator_api/frontend/{node_modules,dist}` | Removed cleanly |
| `rm -rf bonbon_patient_kiosk/frontend/node_modules` | Removed cleanly |
| `rm -f deploy/pi2_deployment_bundle.tar.gz` | Removed cleanly — confirmed gitignored |

**Spot-check after steps 1-2:** `git status --short` showed zero tracked-file changes from any of the above — confirmed 100% of this step touched only gitignored/generated content.

## 3. Quarantine uncertain files

| Action | Result |
|---|---|
| `git mv ros2_ws/src/bonbon_perception _archive/quarantine_cleanup_20260814/bonbon_perception` | Moved, tracked as a rename in git |
| `git mv` × 9 for the dead hand-tracking assets → `_archive/.../models_hands/` | Moved, tracked as renames |
| `git mv` × 2 for the orphaned package launch files → `_archive/.../` | Moved, tracked as renames |

## 4. Fix dangerous direct-control paths

None found in Phase 5 — nothing to do here. See `DANGEROUS_CODE_AUDIT.md`/`SAFETY_BYPASS_REPORT.md`.

## 5. Remove duplicate service topology

The only confirmed duplicate (`bonbon_perception`) was already handled in step 3. No other duplicate pipeline was found (`DUPLICATE_PIPELINE_REPORT.md`).

## 6. Merge duplicate utilities

Deliberately NOT done — the one real finding (`bonbon_operator_api`/`bonbon_patient_kiosk` auth-layer duplication) requires new cross-role test coverage to merge safely, out of scope for a cleanup pass. Flagged for a dedicated future task in `REDUNDANT_CODE_REMOVAL_PLAN.md`.

## 7. Remove dead APIs/endpoints

Deliberately NOT done as outright removal — reclassified to quarantine-and-ask (Tier 3 in `QUARANTINE_REPORT.md`) rather than deletion, since these represent substantial real backend investment (`config_api.py`, `memory_api.py`, `ai_model_status_api.py`, `edge_ai_status_api.py`, `hardware_telemetry_api.py`, 28 WebSocket channels) rather than accidental cruft. The one channel that WAS a genuine truthfulness bug (`live-logs`, advertised with zero producer) was removed in step 10.

## 8. Remove unused dependencies

| Action | Result |
|---|---|
| Removed `torchaudio`, `python-multipart` from `requirements/pi2_requirements.txt` | Edited |
| Removed `@mediapipe/hands`, `@tensorflow-models/hand-pose-detection` from `frontend/package.json` | Edited |
| Fixed `@types/react`/`@types/react-dom` version mismatch (were pinned to React 19 types against a React 18 runtime) | Edited |
| Regenerated `package-lock.json` (`npm install --package-lock-only`) | Confirmed both removed packages dropped from the lockfile (174 lines removed net) |
| Full `npm install` + `npm run build` (`tsc --noEmit && vite build`) | **Passed** — clean TypeScript type-check and production build, direct proof all three dependency changes are correct |
| Cleaned up the verification-only `node_modules`/`dist` afterward | Removed again, consistent with step 2 |

## 9. Clean configs/launch files

| Action | Result |
|---|---|
| `docs/modules.md`: replaced the `bonbon_perception and bonbon_vision` section with a `bonbon_vision`-only section noting the quarantine | Edited |
| `docs/overview.md`: updated the package-families list to drop `bonbon_perception`, with a quarantine note | Edited |
| `diagnostics_api.py`'s `_RESTARTABLE_MODULES`: replaced the now-nonexistent `"bonbon_perception"` entry with `"bonbon_vision"` (the actual live perception/camera package) | Edited, re-tested |

## 10. Fix dashboard truthfulness

Already executed in full during Phase 9 (`restart_module`/`set_config` honest-failure fixes, `live-logs` channel removal) — not repeated here. See `DASHBOARD_FIX_REPORT.md`.

## 11. Run tests after each major category

- After step 8 (dependency changes): `npm run build` — passed (see above).
- After step 9 (`_RESTARTABLE_MODULES` fix): `pytest ros2_ws/src/bonbon_operator_api/tests/test_diagnostics.py` — 23/23 passed.
- After Phase 9's fixes: full `bonbon_operator_api` suite — 246/246 passed (recorded in Phase 9, re-confirmed applicable here since no further changes touched that package after that run except the `_RESTARTABLE_MODULES` edit, itself re-tested above).
- Comprehensive full-repo regression (all packages, all categories combined): Phase 12, next.
