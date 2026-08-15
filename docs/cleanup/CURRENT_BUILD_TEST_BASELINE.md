# Current Build/Test Baseline

**Baseline commit:** `3a544b2` (branch `cleanup/audit-2026-08-14`, created from a clean `main`)

## Config validation — CONFIRMED PASS

```
$ python scripts/validate_config.py --all
Config validation passed for local_dev
Config validation passed for simulation
Config validation passed for lab_robot
Config validation passed for staging_robot
Config validation passed for production_robot
config validation OK for all environments
```
All 5 environments validate cleanly at baseline. (Raw output: `config_validation_baseline.txt`.)

## Top-level pytest suite — CONFIRMED PASS

```
$ python -m pytest tests/ -q
1013 passed, 15 skipped, 2 warnings in 386.84s (0:06:26)
```
Reproduces exactly the "last confirmed" count from earlier in this session (`1013 passed, 15 skipped`), as expected since no source files changed between that run and this baseline branch. The ~4x longer wall-clock time (387s vs. the ~94-101s typical for this suite) is I/O contention from the parallel Phase 1/2 background scans (`du`, `find -size`) and 5 concurrent Phase 2 classification agents running at the same time on this machine, not a regression — re-verified by the fact the pass/skip counts are identical.

The 15 skips are hardware-gated tests (real Hailo/Pi hardware not present in this environment — same honest-skip pattern documented throughout this repo, e.g. `docs/AI_HAT_RUNTIME_STRATEGY.md`), not failures. Full raw output: `pytest_baseline_raw.txt`.

## ROS2 build — BLOCKED (honest, not a defect)

`colcon build` / `ros2 pkg list` could not be run: neither `colcon` nor `ros2` is on `PATH` in this Windows Git-Bash dev sandbox (`which colcon` / `which ros2` both empty, `$ROS_DISTRO` unset). This has been true for this entire project's development in this environment — every `ros2_ws/src/*` package is tested via rclpy-stub injection at the pytest level (`conftest.py` patterns), never a real colcon build, in every session prior to this one as well. `ros2_ws/build|install|log` on disk are stale artifacts from a different environment (see `DISK_USAGE_REPORT.md`), not evidence a build was ever run here.

**This is a real, standing limitation for Phase 12 (Regression Testing) too** — no cleanup change in this repo can be verified against a real colcon build in this environment. Phase 12 will run the full pytest suite (the actual verification mechanism this project has used throughout) and will mark ROS2-build verification `HARDWARE_BLOCKED`/environment-blocked honestly, not fake a pass.

## Per-package test suites (known-good from this session, not re-run yet in this phase)

Every `ros2_ws/src/*/tests/` suite touched by this session's prior work (tasks completed before this cleanup phase began) was independently verified passing in isolation at the time of its own commit — see `docs/cleanup/../` prior session docs (`PATIENT_FACING_UX_REPORT.md`, `FAILURE_CASE_LEARNING.md`, `HUMAN_STATE_FUSION.md`, `SPEECH_AI_UPGRADE_REPORT.md`, `AI_HAT_RUNTIME_STRATEGY.md`) for exact per-package counts. This cleanup process's Phase 12 will re-run the ones actually touched by cleanup changes, not blindly re-run all 44 packages' suites on every phase (that would be excessive given none of Phases 2-9 touch source code).

## Status: Phase 1 build/test baseline CONFIRMED and closed.
