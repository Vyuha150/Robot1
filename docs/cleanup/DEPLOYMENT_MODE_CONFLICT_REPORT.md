# Deployment Mode Conflict Report

**Phase 8.** The most important finding of this phase: there are **three generations of launch mechanism** in this repo, only one of which is what real hardware actually runs. This report traces all three and states, definitively, which is authoritative.

## The three generations

### Generation 1: `*_bringup` packages (`bonbon_bringup`, `bonbon_human_ai_bringup`, `bonbon_ui_api_bringup`, `bonbon_patient_kiosk_bringup`, `bonbon_navigation_bringup`)
Each composes a full per-target application stack by including individual package launch files. Well-documented, internally consistent, genuinely runnable via `ros2 launch <bringup_pkg> <file>.launch.py`.

### Generation 2: `launch/edge_ai/{ai,nav,ui}_pi_edge.launch.py`
Built during the "Edge AI Runtime" work (an earlier phase of this project's development), these launch the edge-AI infrastructure layer (task router, hardware telemetry, network monitor) plus, on the nav Pi, the safety chain. Referenced by `scripts/edge_ai/start_{ai,nav,ui}_pi.sh`.

### Generation 3 (AUTHORITATIVE — what real hardware actually runs today): `deployment/systemd/pi{1,2,3}/*.service` → `docker-compose.pi{1,2,3}.yml`
Confirmed via direct inspection of every `ExecStart` line: **every real systemd unit on every Pi invokes `docker compose -f docker-compose.pi{N}.yml up -d <single-service-name>`** — never a `ros2 launch` command directly, never `scripts/edge_ai/start_*.sh`. Each docker-compose service then runs, inside its own container, exactly one `ros2 launch <package> <specific-launch-file>.launch.py` call, or (for the liveness/monitoring cluster) a small set of direct `ros2 run` commands backgrounded together in one container.

## What Generation 3 actually launches, per Pi (ground truth)

**Pi-1** (`docker-compose.pi1.yml`): `dashboard-api` (uvicorn), `dashboard-frontend` (kiosk script, not compose), `ros2-support` — which directly runs `bonbon_fault_manager fault_manager.launch.py` + `ros2 run bonbon_distributed_safety distributed_safety_node --ros-args -p self_id:=pi1` + `ros2 run bonbon_authority_manager authority_manager_node --ros-args -p self_id:=pi1` + `ros2 run bonbon_distributed_network_monitor network_monitor_node --ros-args -p pi_role:=ui_supervisor_pi`.

**Pi-2** (`docker-compose.pi2.yml`, 10 services): `hal` (camera/mic/speaker-scoped, see device passthrough below), `asr`, `vision`, `perception-fusion`, `llm`, `behavior-engine`, `tts`, `distributed-liveness` (same `distributed_safety`/`authority_manager`/`network_monitor` trio as pi1, `self_id:=pi2`/`pi_role:=ai_interaction_pi`), `dashboard-api`, `dashboard-web`.

**Pi-3** (`docker-compose.pi3.yml`, 7 services): `safety` (`ros2 launch bonbon_safety safety.launch.py`), `hal` (motor/servo/lidar-scoped, `launch_camera:=false launch_mic:=false launch_speaker:=false` — explicitly disabling the device classes Pi-2 owns), `base-controller`, `actuation`, `motion-gateway`, `navigation`, `distributed-liveness` (same trio, `self_id:=pi3`/`pi_role:=navigation_safety_pi`).

## The conflict, precisely stated

**Generations 1 and 2 are real, tested code that is not what deploys to hardware.** Neither `*_bringup` packages nor `launch/edge_ai/*.launch.py` are referenced anywhere in the Generation-3 chain (confirmed: zero `hardware_telemetry`/`edge_ai` string matches in any of the 3 real compose files; zero `IncludeLaunchDescription` of any bringup package found from any compose command). This means:

- `bonbon_hardware_telemetry`'s node and `bonbon_edge_ai_runtime`'s task-router node are **not currently running on real deployed hardware**, despite being real, tested, correctly-wired-into-*something* code with a working dashboard consumer already built for the former. See `FILE_CLASSIFICATION_MATRIX.md`'s corrected entry.
- `bonbon_distributed_network_monitor`'s node **is** genuinely running in production — just via Generation 3's `distributed-liveness`/`ros2-support` services' direct `ros2 run`, completely independent of Generation 2's launch files that also (redundantly) wire it in.
- The two orphaned package-level launch files found in `BROKEN_CODE_REPORT.md` (`bonbon_authority_manager/launch/authority_manager.launch.py`, `bonbon_distributed_safety/launch/distributed_safety.launch.py`) are orphaned precisely because Generation 3 launches these nodes via inline `ros2 run`, not via either package's own launch file — a fourth, even more minimal pattern for just these two nodes.

## No duplicate safety/camera/mic/lidar/motor pipeline in the REAL deployed system

Cross-checked Generation 3 directly (not Generations 1/2, since they don't run): Pi-3's `hal` service is the only one with `launch_camera`/`launch_mic`/`launch_speaker` unset-by-omission... actually explicitly `:=false` — Pi-2's `hal` service owns those device classes exclusively (`/dev/snd` ReSpeaker passthrough, OAK-D camera cgroup rule). `bonbon_safety`'s `safety.launch.py` runs exactly once, only on Pi-3. No service on any Pi duplicates another Pi's hardware ownership. **The hard rules verified in `DUPLICATE_PIPELINE_REPORT.md` hold in the real deployed system, not just in the abstract package-dependency graph.**

## Recommendation for Phase 10/11

This is a documentation and dead-launch-file cleanup matter, not a safety matter — the real deployed system is correct and non-duplicative. Recommend:
1. Update `docs/` wherever it describes `launch/edge_ai/*.launch.py` or `scripts/edge_ai/start_*.sh` as "the" deployment mechanism, to instead point at the real Generation-3 chain, OR decide to formally wire `hardware_telemetry`/`edge_ai_runtime` into the real `docker-compose.pi{2,3}.yml` files if their capability is wanted in production (a feature decision, not a cleanup one).
2. `launch/edge_ai/*.launch.py` and `scripts/edge_ai/start_*.sh` should be QUARANTINE_UNVERIFIED, not REMOVE — they represent real, working code for a deployment path that may still be intended for future use (e.g. a non-Docker bare-metal deployment mode), not confirmed abandoned. Ask before removing.
3. The two orphaned package-level launch files (`authority_manager.launch.py`, `distributed_safety.launch.py`) can be safely removed or documented as intentionally-unused — Generation 3 never needs them, having its own inline `ros2 run` pattern for those two nodes specifically.
