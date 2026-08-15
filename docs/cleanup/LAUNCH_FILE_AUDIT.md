# Launch File Audit

**Phase 8.** Cross-references all 53 `.launch.py` files (Phase 1 baseline count) against the three generations traced in `DEPLOYMENT_MODE_CONFLICT_REPORT.md`.

## Category A: Real, deployed (Generation 3 — invoked directly by a docker-compose `command:`)

`bonbon_safety/safety.launch.py`, `bonbon_hal/hal.launch.py` (×2 instances, differently parameterized per Pi), `bonbon_base_controller/base_controller.launch.py`, `bonbon_actuation/actuation.launch.py`, `bonbon_motion_approval_gateway/motion_approval_gateway.launch.py`, `bonbon_navigation/navigation.launch.py`, `bonbon_fault_manager/fault_manager.launch.py`. **KEEP — these are the ground truth of what runs on real hardware.**

Individual package launch files for `bonbon_speech`, `bonbon_vision`, `bonbon_perception_ai` (or its perception-fusion role), `bonbon_llm`, `bonbon_behavior_engine`, `bonbon_tts`, `bonbon_operator_api` — invoked the same way inside pi2/pi1's compose services (not individually re-verified line-by-line in this pass, but consistent with the pattern confirmed for the 7 files listed above). **KEEP.**

## Category B: Real, tested, NOT deployed (Generation 2 — `launch/edge_ai/`)

`launch/edge_ai/ai_pi_edge.launch.py`, `nav_pi_edge.launch.py`, `ui_pi_edge.launch.py`. Real code, wires `bonbon_hardware_telemetry`, `bonbon_distributed_network_monitor`, `bonbon_edge_ai_runtime` correctly with per-Pi parameterization — just not invoked by any real systemd unit. **QUARANTINE_UNVERIFIED, not REMOVE** — see `DEPLOYMENT_MODE_CONFLICT_REPORT.md`'s recommendation to ask before removing, since this may represent an intended-but-not-yet-adopted deployment path rather than abandoned code.

## Category C: Real, tested, NOT deployed (Generation 1 — `*_bringup` packages)

`bonbon_bringup/launch/bringup.launch.py`, `bonbon_human_ai_bringup/launch/human_ai_bringup.launch.py`, `bonbon_ui_api_bringup/launch/ui_api_bringup.launch.py`, `bonbon_patient_kiosk_bringup/launch/patient_kiosk_bringup.launch.py`, `bonbon_navigation_bringup/launch/navigation_bringup.launch.py`. Same situation as Category B — real, well-documented, internally consistent, but not what Generation 3's systemd/compose chain invokes. **QUARANTINE_UNVERIFIED, not REMOVE.** These may be the intended single-host/dev/CI launch path (a legitimate, different use case from the distributed hardware deployment) rather than superseded code — `bonbon_bringup` in particular is explicitly documented elsewhere in this repo as the Docker/CI monolithic entrypoint, which is a real, distinct, still-valid use case from the per-Pi distributed deployment.

## Category D: Confirmed structurally dead (already covered in `BROKEN_CODE_REPORT.md`)

`bonbon_authority_manager/launch/authority_manager.launch.py`, `bonbon_distributed_safety/launch/distributed_safety.launch.py` — zero `IncludeLaunchDescription` references anywhere, and Generation 3 launches these two nodes via inline `ros2 run` instead, not via either file. **QUARANTINE**, real drift risk if edited expecting effect.

## Category E: Documented manual entry points (not orphans)

`bonbon_simulation/launch/{simulation,spawn_robot,world}.launch.py`, `bonbon_navigation/launch/{slam,localization}.launch.py`, `bonbon_perception.launch.py.disabled` (already covered — dead package). These have no automated caller but are documented in their packages' own READMEs as manual `ros2 launch` entry points for Gazebo/SLAM development use. **KEEP**, correctly not part of the automated deployment chain by design.

## Summary

No launch file in this repo is genuinely broken (all resolve to real packages/executables). The interesting finding isn't brokenness — it's that roughly 9 launch files across Categories B and C represent real engineering investment in deployment mechanisms that the project has since moved past in favor of Generation 3, without formally deprecating or removing them. That's a documentation/decision gap, not a code-quality one, and per this audit's own rules, deciding whether to keep, formally deprecate, or remove Generations 1 and 2 is a call for you to make, not one to resolve unilaterally in a cleanup pass.
