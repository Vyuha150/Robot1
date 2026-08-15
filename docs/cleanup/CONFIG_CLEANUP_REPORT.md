# Config Cleanup Report

**Phase 8.** Audits `config/`, the deployment profiles, and the real (Generation 3) compose files for conflicting modes, mock-in-production risk, hardcoded paths, and unsafe defaults.

## Mock mode in production: not found

Grepped the two safety/hardware-bearing real compose files (`docker-compose.pi2.yml`, `docker-compose.pi3.yml`) for any mock/debug flag. The only two hits are informational comments, not active configuration: one documents a previously-fixed bug (a speaker driver that used to fall back to a mock bridge, now fixed to use the real `bonbon_hal.SpeakerDriver`), the other is `dashboard-api`'s own honest self-note that it would show offline/mock data if something were misconfigured — a truthfulness safeguard being documented, not evidence of a problem. Pi-3's `hal` service explicitly sets `driver_mode:=real` (not defaulted, not left as `mock`) for the safety-critical hardware layer. **No mock-in-production risk found.**

## Config file ownership: consistent, no duplication

`config/` (26 YAML/XML files across `distributed/`, `edge_ai/`, `hardware_telemetry/`, `models/`, `runtime/`) is the single source of runtime configuration — confirmed in Phase 2 (`FOLDER_OWNERSHIP_MAP.md`) as loaded by launch files and Dockerfiles, with no competing config location found. `config/distributed/pi_navigation_safety.yaml` and `config/edge_ai/safety_separation.yaml` correctly gate safety-relevant behavior; neither has a sibling/duplicate file elsewhere in the repo.

## Hardcoded paths: one class found, documented as intentional

`deployment/docker/Dockerfile.ai` and the real compose files reference absolute paths like `/opt/bonbon/install`, `/etc/bonbon`, `/var/log/bonbon`, `/var/lib/bonbon` — these are hardcoded, but consistently so across every service and explicitly the deployment convention this repo uses (not per-developer machine paths, not accidentally environment-specific). Not flagged as a cleanup issue; this is standard practice for a fixed-purpose embedded deployment target, not a portability bug.

## Unsafe defaults: none found in the real deployment path

Every service in the real (Generation 3) compose files that touches hardware or safety sets its mode explicitly (`driver_mode:=real`, explicit `launch_camera`/`launch_mic`/`launch_speaker` booleans per Pi) rather than relying on a package-level default that could silently differ between dev and production. `bonbon_data_feedback`'s `debug_mode_enabled` (governs whether raw snapshots are persisted) defaults to `false` at the package level per its own params YAML — the safe default.

## Missing environment variables: not exhaustively checked

Full validation that every `env_file: /etc/bonbon/bonbon.env` reference has all required keys present on real hardware would require access to that file on the actual Pi (not available in this dev sandbox) — flagged as out of scope for this pass rather than guessed at.

## Duplicate Safety Supervisor service: confirmed absent

Already established in `DUPLICATE_PIPELINE_REPORT.md` and re-confirmed in `DEPLOYMENT_MODE_CONFLICT_REPORT.md`'s direct compose-file inspection: `bonbon_safety`'s `safety.launch.py` runs exactly once, only in Pi-3's `safety` service. No config file or compose service defines a second instance.

## The one real "conflicting mode" finding: carried forward from Phase 8's other documents

The Generation 1/2/3 launch-mechanism situation (see `DEPLOYMENT_MODE_CONFLICT_REPORT.md`) is this phase's substantive finding — not a config-file conflict per se, but a deployment-mode ambiguity: which launch generation is authoritative for which of the brief's 5 required modes isn't fully documented anywhere in the repo. Not re-litigated here; see that report and `SYSTEMD_SERVICE_AUDIT.md` for the full analysis and the two flagged open decisions (legacy flat services' fate, single-board dev mode's authoritative definition).
