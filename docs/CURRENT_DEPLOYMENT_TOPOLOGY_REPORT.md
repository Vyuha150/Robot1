# Current Deployment Topology Report (Phase 1 — read-only)

**Date:** 2026-06-30
**Method:** Direct inspection of systemd units, compose files, launch files,
the bringup launch, the safety package, and config profiles. No code changed.

## systemd units present (`deployment/systemd/`)

| Unit | Compose service started | What that service runs |
|---|---|---|
| `bonbon-core.service` | `up -d core` | `ros2 launch bonbon_bringup bringup.launch.py` — **the entire stack** |
| `bonbon-safety.service` | `up -d safety` | `ros2 launch bonbon_safety safety.launch.py` |
| `bonbon-navigation.service` | `up -d navigation` | navigation image |
| `bonbon-perception.service` | `up -d perception` | `bonbon_perception_ai perception.launch.py` |
| `bonbon-speech.service` | `up -d speech` | `bonbon_speech speech.launch.py` |
| `bonbon-tts.service` | `up -d tts` | `bonbon_tts tts.launch.py` |
| `bonbon-dashboard.service` | `up -d dashboard-api` | operator API |
| `bonbon-monitoring.service` | `up -d monitoring` | Prometheus |

**Missing units the modular-production spec needs:** there is **no**
`bonbon-hal`, `bonbon-behavior`, or `bonbon-actuation` systemd unit. In the
current design those subsystems exist *only* inside `bonbon-core`'s full
bringup — so a "modular" deployment built from the current units cannot
bring up HAL/behavior/actuation as independent services. This is a gap
Phase 2 must close.

## compose services present (`deployment/compose/docker-compose.robot.yml`)

9 services: `core`, `navigation`, `ai`, `perception`, `speech`, `tts`,
`safety`, `dashboard-api`, `monitoring`. Note `core` runs the full bringup
(and carries the Pi hardware device passthrough); `ai` exists but no systemd
unit starts it; `safety` was hardened last pass (`oom_score_adj: -900`,
`cpu_shares: 4096`).

## What `bonbon-core` actually launches

`bringup.launch.py` includes, in order: `bonbon_data_stores`, **`bonbon_safety`**,
`bonbon_hal`, `bonbon_vision`, `bonbon_speech`, the AI group (`bonbon_spatial`,
`bonbon_object_intelligence`, `bonbon_multi_person_tracker`,
`bonbon_affective_ai`, `bonbon_gesture`, `bonbon_speaker_intelligence`,
`bonbon_human_state_fusion`, **`bonbon_perception_ai`**, `bonbon_llm`),
`bonbon_behavior_engine`, `bonbon_perception_efficiency`,
`bonbon_data_feedback`, `bonbon_actuation`, navigation (group),
`bonbon_tts`, `bonbon_operator_api` (group).

→ `core` already contains a safety supervisor, perception, speech, tts, and
navigation. Every separate per-subsystem service is therefore a **second
copy** of something already inside `core`.

## The documented enable flow (`deployment/docs/systemd_setup.md`)

```
sudo systemctl enable bonbon-core bonbon-safety bonbon-dashboard bonbon-monitoring
```
and a "recommended start order" listing `bonbon-core` (step 2) **and**
`bonbon-safety` (step 3) **and** `bonbon-perception`/`bonbon-speech`/
`bonbon-tts` (steps 5-7).

→ Following this literally enables `bonbon-core` (= safety+perception+speech+
tts inside it) **together with** the standalone `bonbon-safety` (and the
start-order text implies the others too). This is the duplicate-topology
defect — fully detailed in `DUPLICATE_PIPELINE_RISK_REPORT.md`.

## ordering / priority enforcement today

- `bonbon-navigation`: `Requires=bonbon-safety` + `After=bonbon-safety bonbon-core` (good — gated behind safety).
- `bonbon-tts`: `After=bonbon-core bonbon-safety`.
- `bonbon-core`, `bonbon-perception`, `bonbon-speech`, `bonbon-dashboard`: **no** `After/Requires` on safety — they are not guaranteed to start after the safety supervisor.
- Container runtime priority: only the `safety` compose service has it (`oom_score_adj`/`cpu_shares`, added last pass). No other service is de-prioritised relative to it, but a 4× cpu_shares advantage already gives safety scheduling priority over the default-weighted AI containers.

## config profiles (`devops/config/`)

5 environment profiles: `local_dev`, `simulation`, `lab_robot`,
`staging_robot`, `production_robot` — each with `runtime.env` + `services.yaml`
(+ `models.manifest` for the robot ones). **None of them encode a "deployment
mode" (monolithic vs modular)** — that concept does not exist yet; the
mode is determined purely by *which systemd units an operator happens to
enable*, with no guard. Phase 2 introduces an explicit, validated mode.

## Verdict

The deployment has the *building blocks* for both a monolithic and a modular
topology, but no single source of truth selecting between them and no guard
preventing the two from being enabled simultaneously — which is exactly the
duplicate-safety-supervisor blocker. The modular path is also incomplete
(no HAL/behavior/actuation units).
