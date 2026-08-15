# Cleanup Baseline Report

**Date:** 2026-08-14
**Branch:** `cleanup/audit-2026-08-14` (created from `main` at commit `3a544b2`, working tree clean at time of branch creation)
**Scope:** Phase 1 of the 13-phase full-codebase cleanup audit. This document is the frozen snapshot everything else in `docs/cleanup/` is measured against — no source files are modified in this phase.

## Environment caveats (read before trusting any number below)

- This is a **Windows dev sandbox** (Git Bash / MSYS), not a Pi and not a Linux CI box. `colcon` and `ros2` CLI tools are **not installed here** — confirmed via `which colcon` / `which ros2`, both empty. All ROS2-dependent code in this repo is tested via rclpy stub injection (`conftest.py` patterns across `ros2_ws/src/*/tests/`), not a real ROS2 build. This has been true for the entire project, not something new to this audit.
- `du` (recursive disk-usage summing) is **impractically slow** in this environment for `.venv/` (10,760+ files) and `ros2_ws/build|install|log` (2,400+ files) — likely NTFS/antivirus stat overhead under Git Bash. Where a full recursive sum could not complete, this report uses `find`-based file counts and per-directory (non-recursive) sizes instead, which are equally trustworthy for this audit's purpose (nothing here depends on byte-exact totals).
- No hardware (Pi, LiDAR, Hailo AI HAT, cameras, motors) is attached to this environment. Any cleanup decision that depends on hardware presence is marked `BLOCKED_NEEDS_HARDWARE_CONFIRMATION` in later phases, never guessed.

## Repository identity

- Git remote: `origin` → (see `git remote -v`; not reproduced here to avoid embedding a possibly-private URL in a generated doc — check directly if needed)
- Total commits on `main` at baseline: **130**
- Working tree at baseline: clean (0 modified/untracked files) — confirmed by `git status` immediately before creating the cleanup branch.
- Most recent commit: `3a544b2` — "Add hardware telemetry + network monitor packages; fix 9 real bugs for India deployment readiness" (this session's prior work).

## Top-level repository structure (confirmed via `find . -maxdepth 1`)

```
.claude/                    - Claude Code project config (skills, agents)
.dockerignore, .env.example, .gitattributes, .gitignore
.github/                    - CI workflow config
.mypy_cache/  .pytest_cache/  .ruff_cache/   - generated tool caches (gitignored, see below)
.venv/                      - local Python virtualenv (gitignored, NOT part of git-tracked repo)
Bonbon-robot/                - ANOMALY: see "Notable findings" below
bonbon_behavior_validation/ - top-level Python package (production scenario validation framework)
bonbon_field_learning/      - top-level Python package (simulation-only field-pilot learning loop, no rclpy)
config/                     - runtime YAML configs (per-environment, per-package)
deploy/                     - Pi-2 deployment artifact bundle (tarball + manifest, one-off from a prior deploy session)
deployment/                 - deployment ENGINEERING tree (compose, docker, docs, monitoring, ota, scripts, security, systemd)
devops/                     - devops scripts/tests
docker-compose.dev.yml, docker-compose.robot.yml, docker-compose.simulation.yml  - ROOT-LEVEL compose files
docs/                       - project documentation (very large — 100+ files from this project's iterative development)
founder_command_center/     - separate backend+frontend+docs app; purpose not yet confirmed as BonBon-related (Phase 2)
launch/                     - top-level multi-package launch files (edge_ai/, etc.)
models/                     - model artifacts, 61M (see Disk Usage Report)
pyproject.toml, pytest.ini
requirements/                - contains only `pi2_requirements.txt`
ros2_ws/                    - the ROS2 workspace: src/ (44 packages, real source), build/ install/ log/ (colcon-generated, gitignored)
samples/                    - sample data, 304K
scripts/                    - deployment/ops/model-download scripts
tests/                      - top-level cross-package test suite (1013 tests as of the prior session's final run)
```

## Notable findings surfaced already during baseline collection

These are **observations for Phase 2/3/6 classification, not decisions** — nothing has been touched.

1. **`Bonbon-robot/` is an empty, uninitialized nested git repository.** `ls -la` shows only a `.git` directory; `git log` inside it reports "your current branch 'main' does not have any commits yet"; its only remote is `https://github.com/Vyuha150/Bonbon-robot.git`. Zero source files, zero commits. Strong candidate for `REMOVE_DEAD` pending Phase 2 confirmation — flagged, not removed.
2. **`deploy/` vs `deployment/` naming collision.** `deploy/` (709K) holds a one-off Pi-2 deployment artifact bundle (`pi2_deployment_bundle.tar.gz`, manifest, exclude list, benchmark JSON) from a prior deployment session. `deployment/` (320K) is the real, structured deployment engineering tree (compose/docker/systemd/security/monitoring/ota). These serve different purposes but the near-identical names are a real source of confusion — flagged for Phase 2/8, not merged or renamed yet.
3. **Two sets of docker-compose files.** Root-level `docker-compose.{dev,robot,simulation}.yml` (3 files) coexist with `deployment/compose/docker-compose.{dev,robot,simulation,pi1,pi2,pi3}.yml` (6 files). Whether the root-level set is stale/superseded or serves a distinct purpose (e.g. local single-machine dev vs. Pi-targeted) is a Phase 3/8 duplicate-pipeline question, not resolved here.
4. **`ros2_ws/build`, `ros2_ws/install`, `ros2_ws/log` are real, gitignored, colcon-generated artifacts** (2,178 / 158 / 85 files respectively — confirmed via `find -type f | wc -l`), dated May 26, predating this session and predating the "no colcon in this environment" fact confirmed above — meaning these were generated on a different machine/environment (or an earlier WSL setup) and are now stale relative to current source. Zero git tracking. Strong `REMOVE_GENERATED_CACHE` candidate for Phase 6/11.
5. **Hundreds of scattered `__pycache__/` and per-package `.pytest_cache/` directories** exist under nearly every `ros2_ws/src/*/` package plus `tests/`, `scripts/`, `bonbon_behavior_validation/`, `bonbon_field_learning/`, `devops/`, `launch/edge_ai/` — all confirmed gitignored (`git status --ignored=matching`), zero git impact, real local disk usage. Standard `REMOVE_GENERATED_CACHE` candidates.
6. **`founder_command_center/`** is a full backend+frontend+docs app (196K) whose relationship to BonBon is not yet established — needs a real read in Phase 2, not a guess.

## What this baseline does NOT yet contain

- Exact recursive disk usage per top-level folder (full `du -h --max-depth=3` is still running in the background at time of writing due to `.venv`/`ros2_ws` slowness; see `disk_usage_before.txt`, appended when the scan completes).
- Full list of files >5MB (background scan in progress; see `large_files_5mb_plus.txt`).
- Fresh pytest run output for this exact baseline commit (in progress; see `CURRENT_BUILD_TEST_BASELINE.md`, note at top on whether it completed before this phase closed).

These are genuinely still running due to this environment's slow filesystem stat performance, not skipped — they will be folded into Phase 6 (Storage Optimization) and Phase 12 (Regression Testing) regardless, so their absence here does not block starting Phase 2.

## Companion documents (this phase)

- [REPOSITORY_STRUCTURE_AUDIT.md](REPOSITORY_STRUCTURE_AUDIT.md) — package/launch/service/compose inventories
- [DISK_USAGE_REPORT.md](DISK_USAGE_REPORT.md) — sizes confirmed so far
- [CURRENT_BUILD_TEST_BASELINE.md](CURRENT_BUILD_TEST_BASELINE.md) — test/config-validation baseline
