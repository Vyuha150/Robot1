# Boot Topology

**Final rule for this release: there must be exactly one Safety Supervisor
process in every deployment mode.** This is enforced four ways (systemd
`Conflicts=`, mode scripts, a static validator, a runtime check) — see
[SAFETY_SUPERVISOR_SINGLETON_POLICY.md](SAFETY_SUPERVISOR_SINGLETON_POLICY.md)
for the policy statement and [BOOT_TOPOLOGY_FIX_REPORT.md](BOOT_TOPOLOGY_FIX_REPORT.md)
for what was actually broken and how it was fixed. For the full boot
sequence, systemd unit dependency graph, and Pi-specific setup steps, see
[PI_BOOT_TOPOLOGY.md](PI_BOOT_TOPOLOGY.md).

## The two modes

### A. Monolithic development mode

- `bonbon-core.service` enabled — runs `bringup.launch.py` (the whole
  stack, including Safety Supervisor).
- All 8 per-subsystem services (`bonbon-safety`, `bonbon-hal`,
  `bonbon-perception`, `bonbon-speech`, `bonbon-behavior`,
  `bonbon-navigation`, `bonbon-actuation`, `bonbon-tts`) **disabled**.
- Safety runs only inside `bonbon-core`.

```bash
sudo bash scripts/select_deployment_mode.sh monolithic
# equivalent to:
sudo bash scripts/enable_monolithic_mode.sh
```

### B. Modular Raspberry Pi production mode

- `bonbon-core.service` **disabled**.
- `bonbon-safety.service` enabled — the single Safety Supervisor.
- Selected modular services (`bonbon-hal`, `bonbon-perception`,
  `bonbon-speech`, `bonbon-behavior`, `bonbon-navigation`,
  `bonbon-actuation`, `bonbon-tts`) enabled as needed.
- Safety runs only as `bonbon-safety`.

```bash
sudo bash scripts/select_deployment_mode.sh modular_pi
# equivalent to:
sudo bash scripts/enable_modular_pi_mode.sh
```

## Validation

```bash
# static: classify the enabled unit set, exit non-zero on duplicate/missing safety
python3 scripts/validate_boot_topology.py
python3 scripts/validate_boot_topology.py --check-running-nodes   # + live ros2 node list count

# runtime: fails if `ros2 node list` shows != 1 safety_supervisor_node
bash scripts/check_duplicate_ros_nodes.sh
```

Both scripts write/refresh `devops/project-status/boot_topology.json`,
which `GET /api/v1/deployment/boot-topology` and the dashboard's Boot
Topology card read directly — an invalid topology is visible on the
dashboard, with the exact remediation command, not just in a terminal.

## Tests

`devops/tests/test_boot_topology.py` (12 tests, pure Python, no Pi
required): monolithic-mode-valid, modular-Pi-mode-valid, mixed-mode-
INVALID, duplicate-safety-supervisor-detected (both from the static unit
set and from an injected live-node-count override), dashboard
serialization, and remediation-command generation. All 12 pass in this
environment; live confirmation on a booted Pi (`systemctl is-active`,
`ros2 node list`) is BLOCKED without physical hardware — see
[FINAL_PRODUCTION_READINESS_CHECKLIST.md](FINAL_PRODUCTION_READINESS_CHECKLIST.md).
