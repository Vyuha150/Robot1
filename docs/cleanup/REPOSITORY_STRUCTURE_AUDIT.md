# Repository Structure Audit

**Part of Phase 1 (baseline).** Inventories packages, launch files, systemd services, and deployment configs as they exist right now — no judgment calls about redundancy yet (that's Phase 3).

## ROS2 packages (44 total, `ros2_ws/src/`)

```
bonbon_actions, bonbon_actuation, bonbon_affective_ai, bonbon_ai_model_registry, bonbon_ai_runtime,
bonbon_authority_manager, bonbon_base_controller, bonbon_behavior_engine, bonbon_bringup,
bonbon_data_feedback, bonbon_data_stores, bonbon_distributed_network_monitor, bonbon_distributed_safety,
bonbon_edge_ai_runtime, bonbon_fault_manager, bonbon_gesture, bonbon_hal, bonbon_hardware_telemetry,
bonbon_human_ai_bringup, bonbon_human_state_fusion, bonbon_llm, bonbon_motion_approval_gateway,
bonbon_msgs, bonbon_multi_person_tracker, bonbon_navigation, bonbon_navigation_bringup,
bonbon_object_intelligence, bonbon_operator_api, bonbon_patient_kiosk, bonbon_patient_kiosk_bringup,
bonbon_perception, bonbon_perception_ai, bonbon_perception_efficiency, bonbon_safety,
bonbon_sarvam_adapter, bonbon_simulation, bonbon_spatial, bonbon_speaker_intelligence, bonbon_speech,
bonbon_speech_ai, bonbon_srvs, bonbon_tts, bonbon_ui_api_bringup, bonbon_vision
```

Confirmed via `find ros2_ws/src -maxdepth 1 -type d`, cross-checked against `find ros2_ws/src -name package.xml | wc -l` = 44 (exact match, no package missing a manifest).

**Package-name pairs flagged for Phase 3 duplicate-pipeline review** (naming alone suggests possible overlap — not concluded here):
- `bonbon_perception` vs `bonbon_perception_ai` vs `bonbon_perception_efficiency` vs `bonbon_vision`
- `bonbon_speech` vs `bonbon_speech_ai` — **already partially resolved by prior-session work this repo has documented**: `docs/SPEECH_AI_UPGRADE_REPORT.md` (updated in this session, see git history) confirms `bonbon_speech_ai` is real, tested library code that is **not yet wired into** the live `bonbon_speech` ROS2 node — a known, already-documented gap, not a fresh finding. Phase 3 will re-verify this is still accurate rather than re-deriving it from scratch.
- `bonbon_navigation` vs `bonbon_navigation_bringup`, `bonbon_human_ai_bringup` vs `bonbon_ui_api_bringup` vs `bonbon_patient_kiosk_bringup` vs `bonbon_bringup` — bringup packages are commonly *intentionally* thin per-deployment-target wrappers around a shared core package, not necessarily duplicates. Needs a real read, not a name-pattern guess.

## Launch files (53 total under `find . -name "*.launch.py"`)

- **4 top-level multi-package launch files**: `launch/edge_ai/{ai_pi_edge,full_edge_sim,nav_pi_edge,ui_pi_edge}.launch.py` — the real 3-Pi + simulation entry points.
- **34 per-package launch files** under `ros2_ws/src/*/launch/` — one real launch file per package that has one (10 of the 44 packages have no launch file of their own, e.g. `bonbon_msgs`, `bonbon_srvs`, pure interface/library packages — expected, not a gap).
- **15 files under `ros2_ws/build/` and `ros2_ws/install/`** — these are colcon-copied duplicates of 5 source launch files (`bonbon_hal`, `bonbon_perception`, `bonbon_perception_ai`, `bonbon_safety`, `bonbon_speech`, `bonbon_vision`), not independent content. Gitignored, generated. Will be addressed as part of the `ros2_ws/build|install|log` cache-removal candidate in Phase 6, not counted as "real" duplicate launch files.

## systemd services (29 total under `deployment/systemd/`)

Two distinct layers, matching this repo's two documented deployment modes (`docs/ARCHITECTURE_FREEZE.md` §"boot topology"):
- **11 root-level services** (`bonbon-actuation.service`, `bonbon-behavior.service`, `bonbon-core.service`, `bonbon-dashboard.service`, `bonbon-hal.service`, `bonbon-monitoring.service`, `bonbon-navigation.service`, `bonbon-perception.service`, `bonbon-safety.service`, `bonbon-speech.service`, `bonbon-tts.service`) — the monolithic single-machine deployment mode.
- **18 per-Pi services** under `pi1/` (3), `pi2/` (8), `pi3/` (7) — the modular 3-Pi production deployment mode.

Whether both modes' services correctly avoid starting duplicate safety/camera/mic/lidar/motor pipelines when the wrong mode is active is a **Phase 8 question**, not resolved here — flagging that the structural split exists and looks intentional (matches the two-deployment-mode architecture already documented elsewhere in this repo).

## Docker Compose files (9 total)

- **Root-level (3):** `docker-compose.dev.yml`, `docker-compose.robot.yml`, `docker-compose.simulation.yml`
- **`deployment/compose/` (6):** `docker-compose.dev.yml`, `docker-compose.pi1.yml`, `docker-compose.pi2.yml`, `docker-compose.pi3.yml`, `docker-compose.robot.yml`, `docker-compose.simulation.yml`

The root-level `dev`/`robot`/`simulation` names exactly duplicate 3 of the 6 `deployment/compose/` file names. Whether these are (a) genuinely identical/stale duplicates, (b) an older location superseded by `deployment/compose/`, or (c) serve a distinct purpose (e.g. quick top-level `docker compose up` convenience vs. the "real" per-Pi-aware set) is **not determined here** — real content diff deferred to Phase 3/8.

## Dependency manifests found

- `pyproject.toml` (root) — 20 top-level dependency-looking entries (rough grep count, not parsed)
- `requirements/pi2_requirements.txt` — the one file in the top-level `requirements/` directory
- `founder_command_center/backend/requirements.txt` — separate app, separate dependency set
- 44× `ros2_ws/src/*/package.xml` — ROS2-native dependency declarations (build_depend/exec_depend), one per package

Full parse and unused-dependency analysis is Phase 7 scope.

## What's still pending from this phase

`ros2 pkg list` / `colcon list` could not be run — no ROS2 install in this environment (see `CLEANUP_BASELINE_REPORT.md`'s environment caveats). The 44-package `ros2_ws/src/` listing above is the closest honest equivalent obtainable here, and is what Phase 2 onward will use as the "package list of record."
