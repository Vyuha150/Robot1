# Final Deleted Files List

**Phase 13.** Every item permanently deleted in this cleanup (Tier 1 only — see `QUARANTINE_REPORT.md`). All were gitignored/untracked; `git status --short` before and after confirms zero tracked-file impact from any entry below.

| Path | Type | Approx. size | Confirmed gitignored? |
|---|---|---|---|
| `.venv/` | Python virtualenv | 1.6G | Yes (`.gitignore:13`) |
| `.mypy_cache/` | mypy tool cache | 14M | Yes |
| `.ruff_cache/` | ruff tool cache | 2.0M | Yes |
| `ros2_ws/build/` | stale colcon build output | 35M | Yes |
| `ros2_ws/install/` | stale colcon install output | 3.8M | Yes |
| `ros2_ws/log/` | stale colcon log output | 2.0M | Yes |
| `ros2_ws/src/bonbon_operator_api/frontend/node_modules/` | npm dependencies | ~500M+ | Yes (`frontend/.gitignore:1`) |
| `ros2_ws/src/bonbon_operator_api/frontend/dist/` | Vite build output | ~71M | Yes (`frontend/.gitignore:2`) |
| `ros2_ws/src/bonbon_patient_kiosk/frontend/node_modules/` | npm dependencies | ~75M | Yes (`frontend/.gitignore:1`) |
| `deploy/pi2_deployment_bundle.tar.gz` | one-off deployment artifact | 667K | Yes (`.gitignore:40`) |

**`.pytest_cache/`** was targeted for the same treatment but the deletion was **blocked by an OS-level permission denial** (`Permission denied`), the same pre-existing environment quirk documented in Phase 1's baseline (`CURRENT_BUILD_TEST_BASELINE.md`). Not forced through. Left in place, harmless — it's still gitignored and doesn't affect any test outcome.

## What was NOT included in this list

Nothing git-tracked appears here. Every git-tracked item that was moved (not deleted) is in `FINAL_QUARANTINED_FILES_LIST.md` instead. This list contains only generated/regenerable content that never had a permanent place in the repository's actual history.
