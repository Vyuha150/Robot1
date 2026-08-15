# Final Retained High-Risk Files

**Phase 13.** Not a list of problems — a list of the safety-critical / high-consequence files this cleanup specifically reviewed and explicitly kept, with the evidence for why removing, moving, or modifying them was never on the table. Required by the brief's non-negotiable rule: "Do not delete safety-critical files without proof."

## Tier: Safety-critical, verified sole-authority, untouched

| File/Package | Role | Verification |
|---|---|---|
| `bonbon_safety/nodes/safety_supervisor_node.py`, `safety_gate_node.py`, `estop_node.py`, `watchdog_node.py` | THE Safety Supervisor + Safety Gate; sole publisher of `/cmd_vel` and gated actuator commands | `SAFETY_BYPASS_REPORT.md` — direct grep confirmed no other publisher of these topics exists anywhere in 44 packages |
| `bonbon_motion_approval_gateway/` | THE Safety Gateway; sole subscriber of proposal topics, fail-closed on missing SafetyState | Same report |
| `bonbon_hal/` (all drivers) | Sole hardware-write layer; motor/servo/stepper only reachable via gated topics | Same report; zero bypass path found |
| `bonbon_navigation_bringup/launch/navigation_bringup.launch.py` | Encodes the correct safety→HAL→controller→actuation→gateway→navigation boot order | `FILE_CLASSIFICATION_MATRIX.md` safety cluster |
| `deployment/systemd/pi3/bonbon-pi3-safety.service`, `bonbon-pi3-hal.service`, `bonbon-pi3-motion-gateway.service` | Real, currently-deployed systemd units for the above | `SYSTEMD_SERVICE_AUDIT.md`, `DEPLOYMENT_MODE_CONFLICT_REPORT.md` |
| `config/distributed/pi_navigation_safety.yaml`, `config/edge_ai/safety_separation.yaml` | Gate real safety behavior | `CONFIG_CLEANUP_REPORT.md` |

None of these were modified, moved, or even considered for quarantine at any point in this cleanup — they're listed here as the positive record that they were checked, not skipped.

## Tier: High-consequence but not safety-critical — reviewed, retained as real capability, deliberately not removed

These aren't dangerous, but removing them would be a product decision with real consequences (losing working dashboard functionality, breaking a documented-but-dormant deployment path) — every one is detailed with its own evidence in `QUARANTINE_REPORT.md`'s Tier 3:

- `bonbon_speech_ai/` — real, tested ASR/TTS routing and hospital-entity-correction code, not yet wired into the live speech node.
- `bonbon_hardware_telemetry`, `bonbon_edge_ai_runtime` nodes — real, tested, wired into a launch mechanism (`launch/edge_ai/`) that isn't the current production deployment path.
- `launch/edge_ai/*.launch.py`, `scripts/edge_ai/start_*.sh` — a complete, working alternate deployment mechanism.
- `bonbon_bringup`, `bonbon_human_ai_bringup`, `bonbon_ui_api_bringup`, `bonbon_patient_kiosk_bringup`, `bonbon_navigation_bringup` — the single-host/dev/CI launch mechanism.
- 11 legacy flat systemd services under `deployment/systemd/` — possibly an intentional single-board dev-mode fallback.
- `config_api.py`, `memory_api.py`, `ai_model_status_api.py`, `edge_ai_status_api.py`, `hardware_telemetry_api.py` (REST) and 28 of 29 WebSocket channels — real backend capability with no frontend UI built yet.
- The `bonbon_operator_api`/`bonbon_patient_kiosk` duplicated auth implementation — real duplication, but a correct merge needs new cross-role test coverage this cleanup pass wasn't scoped to write.

## Tier: Explicitly out of scope by user instruction

- `founder_command_center/` — a confirmed-unrelated CRM/business-ops product with zero coupling to the robot codebase. The user explicitly chose "leave it alone entirely" when asked (2026-08-14). Not reviewed for internal risk by this audit at all — that would exceed the scope the user set.
