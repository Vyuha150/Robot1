# Systemd Service Setup

> **Important:** do **not** hand-enable a mix of `bonbon-core` and the
> per-subsystem services — that boots two safety supervisors (the
> duplicate-pipeline bug). Use the mode scripts below, which enforce exactly
> one. Full detail: [`docs/SYSTEMD_DEPLOYMENT_MODES.md`](../../docs/SYSTEMD_DEPLOYMENT_MODES.md)
> and [`docs/SAFETY_SUPERVISOR_SINGLETON_POLICY.md`](../../docs/SAFETY_SUPERVISOR_SINGLETON_POLICY.md).

Install units:

```bash
sudo cp deployment/systemd/bonbon-*.service /etc/systemd/system/
sudo systemctl daemon-reload
```

Then pick exactly one mode:

```bash
# MODE A — monolithic (simulation / local dev / simple lab):
sudo bash scripts/select_deployment_mode.sh monolithic

# MODE B — modular production (Raspberry Pi):
sudo bash scripts/select_deployment_mode.sh modular_pi
```

Validate at any time (changes nothing):

```bash
bash scripts/select_deployment_mode.sh status
bash scripts/check_duplicate_ros_nodes.sh    # on the robot, sourced workspace
```

The mode scripts disable the conflicting set before enabling the chosen one,
then run `scripts/validate_boot_topology.py`, which fails the deploy on any
duplicate/missing safety supervisor and writes the verdict to
`devops/project-status/boot_topology.json` (surfaced on the dashboard).
