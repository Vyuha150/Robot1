# Systemd Service Audit

**Phase 8.** All 29 systemd `.service` files under `deployment/systemd/` checked.

## Real, currently-deployed services (18 files) — the actual production topology

`deployment/systemd/pi1/*.service` (3), `pi2/*.service` (8), `pi3/*.service` (7) — 18 total. Every one's `ExecStart` resolves to a real `docker compose -f docker-compose.pi{N}.yml up -d <service>` command targeting a service genuinely defined in that compose file (cross-checked directly, not assumed). **KEEP_PRODUCTION**, this is the authoritative deployment layer — see `DEPLOYMENT_MODE_CONFLICT_REPORT.md`.

## Legacy flat services (11 files) — pre-3-Pi-split, already documented as superseded

`deployment/systemd/{bonbon-core,bonbon-actuation,bonbon-behavior,bonbon-dashboard,bonbon-hal,bonbon-monitoring,bonbon-navigation,bonbon-perception,bonbon-safety,bonbon-speech,bonbon-tts}.service`. Already documented in `docs/THREE_PI_RUNTIME_AUDIT.md:133-136` as predating the three-Pi split. Not literally broken (each has a valid `ExecStart`), but confirmed still present alongside the newer per-Pi units, and `devops/scripts/post_deploy_check.py` only checks 8 of these 11 legacy names — meaning even the tooling that verifies deployment health has only partial awareness of which layer is authoritative.

**Recommendation: QUARANTINE, not REMOVE, pending an explicit decision.** These 11 files could represent:
(a) a genuinely obsolete single-Pi-per-service topology fully superseded by the pi1/2/3 split, safe to remove, or
(b) an intentional fallback/single-board deployment mode (the brief's own "single-board dev mode" requirement) that's still meant to work.

Nothing in this audit's evidence distinguishes these two possibilities with certainty — the docs flag them as legacy but don't explicitly say "delete these." This is exactly the kind of item this audit's rules require quarantining and asking about, not guessing on.

## No duplicate-service-per-topology finding

Within the 18 real (Generation 3) services, no Pi runs two services claiming the same hardware/topic ownership — confirmed directly against each compose file's service definitions and device passthrough blocks in `DEPLOYMENT_MODE_CONFLICT_REPORT.md`. Within the 11 legacy services, each also appears to target one subsystem per file (no internal duplication among the 11 themselves) — but since they're not currently running, there was no live conflict to check them against.

## Cross-reference with the brief's "5 required deployment modes"

| Required mode | Found in this repo? |
|---|---|
| Single-board dev mode | Possibly the legacy flat services, or `bonbon_bringup`'s monolithic launch (Generation 1) — not definitively confirmed which is the intended single-board path |
| Three-Pi production mode | ✅ Confirmed — the 18 real Generation-3 systemd/compose services |
| Mock/demo UI mode | Not independently verified in this phase — `docker-compose.dev.yml`/`docker-compose.simulation.yml` (root wrappers into `deployment/compose/`) likely serve this, not re-checked line-by-line here |
| Hardware-gated test mode | ✅ Confirmed — `BONBON_HAILO_HW_TEST=1`-style env-gated tests found throughout the pytest suite (see `CURRENT_BUILD_TEST_BASELINE.md`'s 15 honest skips) |
| Degraded mode | ✅ Confirmed live — `bonbon_edge_ai_runtime`'s degraded-mode manager and `bonbon_authority_manager`'s broadcasts, per `DUPLICATE_PIPELINE_REPORT.md` |

Two of five modes need a follow-up decision (single-board dev mode's authoritative definition, mock/demo mode's exact composition) rather than being fully confirmed in this pass — flagged, not guessed.
