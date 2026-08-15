# Regression Risk Report

**Phase 12.** Assesses residual risk from every change made in this cleanup, independent of the test results in `POST_CLEANUP_TEST_REPORT.md` — i.e. what could still be wrong even though the tests pass, because tests don't cover everything.

## Risk by change category

| Change | Test coverage | Residual risk | Assessment |
|---|---|---|---|
| Cache/build-artifact deletion (`.venv`, `ros2_ws/{build,install,log}`, `.mypy_cache`, `.ruff_cache`, frontend `node_modules`/`dist`) | N/A — gitignored, untracked | **None** — confirmed via `git status` that zero tracked files were affected; all regenerable by standard tooling | Lowest-risk category in this entire cleanup |
| `bonbon_perception` quarantine | Full top-level suite (1013 tests) shows no change from baseline | **Very low** — package was already fully disabled before quarantine (launch file `.disabled`, empty `console_scripts`); moving it changes nothing about what's importable or runnable | If wrong, `RESTORE_PLAN.md` gives an exact one-line `git mv` back |
| Hand-tracking asset + npm package removal | `npm run build` passed cleanly (TypeScript compile + production bundle) | **Low** — direct build verification is strong evidence, but the dashboard frontend wasn't visually smoke-tested in a browser this phase (no `run`/browser-preview step taken) | Recommend a visual smoke-test of the gesture-recognition UI feature before the next real deployment, since that's the feature area nearest the changed code, even though it doesn't touch the removed hand-tracking code path |
| Orphaned launch file quarantine (`authority_manager.launch.py`, `distributed_safety.launch.py`) | Full top-level suite, `bonbon_operator_api` suite | **Very low** — confirmed via Phase 8's direct compose-file inspection that neither file is referenced by the real deployment chain; nothing imports or launches them | If wrong, `RESTORE_PLAN.md` gives exact restore commands |
| `requirements/pi2_requirements.txt` edits (`torchaudio`, `python-multipart` removed) | Not independently pip-installed and tested in this environment (no real Pi-2 hardware/target here) | **Low-medium** — the removal evidence (zero imports repo-wide) is strong, but the actual `pip install -r requirements/pi2_requirements.txt` command that consumes this file wasn't re-run in this environment (would require the real ARM64/ROS2 target this file is written for) | Recommend re-running the real Pi-2 Docker build (`deployment/docker/Dockerfile.ai`) once, on real infrastructure, before the next deployment — this file's own extensive comments show it was previously debugged via exactly this kind of real-build verification, and this cleanup's removals should get the same treatment before being trusted at deploy time |
| `diagnostics_api.py`/`config_api.py` truthfulness fixes | 12 + 23 new/updated tests, full `bonbon_operator_api` suite (246 passed before the final `_RESTARTABLE_MODULES` edit, re-confirmed after) | **Low** — direct test coverage of both the success and failure paths | None identified |
| `live-logs` WebSocket channel removal | Full `bonbon_operator_api` suite including `test_websocket.py` | **Very low** — zero consumers existed (frontend or test) before removal | If a real log-streaming feature is wanted later, re-adding the channel is a 2-line change (both files), not a redesign |
| `_RESTARTABLE_MODULES` fix (`bonbon_perception` → `bonbon_vision`) | `test_diagnostics.py` re-run in isolation (23/23) | **Very low** | None identified |
| Doc edits (`docs/modules.md`, `docs/overview.md`) | N/A — prose only | **None** | No functional risk |

## What this phase did NOT verify (explicitly out of scope, not silently skipped)

- **Real hardware behavior** — no Pi/Hailo hardware in this environment; all hardware-gated tests honestly skip, as they did before this cleanup.
- **The real Pi-2 Docker build with the trimmed `requirements/pi2_requirements.txt`** — see the medium-risk row above.
- **Visual/interactive frontend smoke test** — `npm run build` proves the bundle compiles and produces output; it doesn't prove every UI interaction still renders correctly in a browser. Not performed this phase (no `preview_start`/browser tool used).
- **The Tier 3 items in `QUARANTINE_REPORT.md`** — deliberately untouched, so they carry zero regression risk from this cleanup by construction.

## Overall regression risk: LOW

The strongest evidence is structural: every deletion in Tier 1 was gitignored (zero git-tracked impact by definition), every Tier 2 quarantine target had independent dead-code evidence *and* an intact regression suite afterward, and the three actual code fixes (Phase 9) shipped with dedicated new tests that specifically pin the bug being fixed. The one genuine gap (real Pi-2 build re-verification) is a hardware-dependent step this environment cannot perform, honestly flagged rather than assumed fine.
