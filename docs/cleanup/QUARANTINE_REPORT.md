# Quarantine Report

**Phase 10.** Consolidates every REMOVE/QUARANTINE finding from Phases 2-9 into a concrete before-deletion plan. Per the brief's own rule, only items in the "clearly safe" tier proceed straight to permanent deletion in Phase 11 — everything else is quarantined to `_archive/quarantine_cleanup_20260814/` first, with a restore command, and awaits either the passage of a sanity-check window or an explicit decision from you.

## Tier 1 — Clearly safe, permanent deletion in Phase 11 (no quarantine needed)

These are gitignored, generated, or trivially regenerable — quarantining them would add process overhead with zero risk reduction.

| Item | Why it's safe |
|---|---|
| `.venv/` | Gitignored virtualenv, `pip install` regenerates |
| `ros2_ws/{build,install,log}/` | Gitignored colcon artifacts, stale anyway (no colcon in this environment) |
| `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/` (root + every per-package copy) | Gitignored tool caches |
| `ros2_ws/src/bonbon_operator_api/frontend/{node_modules,dist}/` | Gitignored, `npm install`/`npm run build` regenerate |
| `ros2_ws/src/bonbon_patient_kiosk/frontend/node_modules/` | Same |
| `deploy/pi2_deployment_bundle.tar.gz` | Gitignored local build artifact |

## Tier 2 — Quarantine first, then delete after the sanity window (real, git-tracked content with strong-but-not-absolute evidence of deadness)

| Item | Original path | Reason | Evidence | Restore command |
|---|---|---|---|---|
| `bonbon_perception` package | `ros2_ws/src/bonbon_perception/` | Confirmed dead duplicate of `bonbon_vision` | Disabled launch file, empty `console_scripts`, zero repo-wide imports (`DUPLICATE_PIPELINE_REPORT.md`) | `git mv _archive/quarantine_cleanup_20260814/bonbon_perception ros2_ws/src/bonbon_perception` |
| Hand-tracking asset bundle | `ros2_ws/src/bonbon_operator_api/frontend/public/models/hands/*` (9 files, 3 LFS) | Zero references anywhere in `frontend/src` | `STALE_MOCK_AND_PLACEHOLDER_REPORT.md`, corroborated by 2 unused npm packages (`UNUSED_DEPENDENCY_REPORT.md`) | `git mv _archive/quarantine_cleanup_20260814/models_hands/* ros2_ws/src/bonbon_operator_api/frontend/public/models/hands/` |
| Orphaned package launch files | `ros2_ws/src/bonbon_authority_manager/launch/authority_manager.launch.py`, `ros2_ws/src/bonbon_distributed_safety/launch/distributed_safety.launch.py` | Zero `IncludeLaunchDescription` references; real deployment launches these two nodes via inline `ros2 run` instead | `BROKEN_CODE_REPORT.md` item 5, confirmed by `DEPLOYMENT_MODE_CONFLICT_REPORT.md`'s direct compose-file inspection | `git mv _archive/quarantine_cleanup_20260814/<file> <original path>` |

## Tier 3 — NOT quarantined, NOT touched in this cleanup pass — real capability awaiting an explicit product/engineering decision

These are working, tested (or partially tested) code representing real investment. Removing or even quarantining them risks destroying something intended for future use. Listed here for visibility, deliberately excluded from Phase 11's execution.

| Item | Why it's not being touched |
|---|---|
| `founder_command_center/` | Explicit user decision (2026-08-14): leave alone entirely |
| `bonbon_speech_ai/` (asr_router, tts_router, language_detector, transcript_normalizer, hospital_entity_corrector, speech_pipeline) | Real, tested, working code; not wired into the live `bonbon_speech` node yet. A "wire it in" decision, already documented as a known gap in `docs/SPEECH_AI_UPGRADE_REPORT.md`. |
| `bonbon_hardware_telemetry`'s node, `bonbon_edge_ai_runtime`'s node | Real, tested, wired into `launch/edge_ai/*.launch.py` — but that launch mechanism isn't part of the real production deployment (`DEPLOYMENT_MODE_CONFLICT_REPORT.md`). Dashboard consumer already built for the former. |
| `launch/edge_ai/{ai,nav,ui}_pi_edge.launch.py`, `scripts/edge_ai/start_*.sh` | Real, working alternate deployment mechanism — may represent an intended non-Docker deployment path, not confirmed abandoned |
| `bonbon_bringup`, `bonbon_human_ai_bringup`, `bonbon_ui_api_bringup`, `bonbon_patient_kiosk_bringup`, `bonbon_navigation_bringup` (the `*_bringup` packages) | Real, working single-host/dev/CI launch mechanism, distinct valid use case from the per-Pi distributed deployment |
| 11 legacy flat systemd services (`deployment/systemd/bonbon-*.service`) | Could be an intentional single-board dev-mode fallback (one of the brief's 5 required modes) rather than confirmed-obsolete (`SYSTEMD_SERVICE_AUDIT.md`) |
| `config_api.py`, `memory_api.py`, `ai_model_status_api.py` (12 routes), `edge_ai_status_api.py` (9 routes), `hardware_telemetry_api.py` REST endpoints | Real, substantial backend capability with no frontend UI built for it yet — a dashboard-completeness gap, not dead code. `config_api.py` specifically now has full test coverage as of Phase 9's fix (`test_config_api.py`, 12 tests) |
| 28 of 29 WebSocket channels (`VALID_CHANNELS` minus `robot-status`) | Real, honest, mostly-tested backend broadcasts with no frontend subscriber — same reasoning as above |
| `bonbon_operator_api`/`bonbon_patient_kiosk` auth-layer duplication | Real duplication, but a correct extraction requires new test coverage across both role matrices — a dedicated future refactor task, not a mechanical dedup |
| `deploy/{pi2_manifest.txt,pi2_exclude.txt,pi2_qwen_benchmark_results.json}` | Historical value; recommend relocating to `docs/archive/` rather than deleting — a documentation decision, deferred |
| `docs/modules.md`, `docs/overview.md` | Need an edit (add a quarantine caveat for `bonbon_perception`), not removal — tracked in `STALE_MOCK_AND_PLACEHOLDER_REPORT.md`, addressed as a doc fix in Phase 11, not a deletion |

## Sanity-check window before Tier 2 permanent deletion

Before Phase 11 permanently deletes any Tier 2 item: re-run the full pytest suite with the quarantined files physically absent (not just untracked) and confirm zero new failures, plus a final repo-wide grep for the quarantined path/package name to catch anything the earlier passes might have missed. This is deliberately the same "defense in depth" step already promised in `REDUNDANT_CODE_REMOVAL_PLAN.md` for `bonbon_perception` — applied uniformly to all of Tier 2, not just that one item.
