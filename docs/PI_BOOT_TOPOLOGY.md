# Raspberry Pi Boot Topology

How BonBon boots on a Raspberry Pi 5, end to end, with exactly one safety
supervisor.

## One-time setup on the Pi

```bash
# 1. Hardware present?
bash scripts/pi_hardware_check.sh

# 2. Install systemd units
sudo cp deployment/systemd/bonbon-*.service /etc/systemd/system/
sudo systemctl daemon-reload

# 3. Select the production mode (disables bonbon-core, enables modular set)
sudo bash scripts/select_deployment_mode.sh modular_pi
```

## Boot sequence (modular Pi mode)

```
power on
  └─ systemd multi-user.target
       ├─ docker.service + network-online.target
       └─ bonbon-safety        ← THE safety supervisor (one, only)
            └─ bonbon-hal       ← sensor/actuator drivers, e-stop GPIO
                 ├─ bonbon-perception
                 ├─ bonbon-speech
                 ├─ bonbon-behavior
                 ├─ bonbon-navigation   (Requires bonbon-safety)
                 ├─ bonbon-actuation    (Requires bonbon-safety + bonbon-hal)
                 └─ bonbon-tts
       ├─ bonbon-dashboard
       └─ bonbon-monitoring
```

Nothing that can move (`navigation`, `actuation`) starts before
`bonbon-safety` and `bonbon-hal` are up — enforced by each unit's
`Requires=`/`After=`.

## Confirm a clean boot

```bash
# enabled-unit topology (writes devops/project-status/boot_topology.json)
python3 scripts/validate_boot_topology.py            # expect: mode=modular_pi, valid=True

# exactly one running safety supervisor
python3 scripts/validate_boot_topology.py --check-running-nodes
bash scripts/check_duplicate_ros_nodes.sh            # expect: RESULT clean

# all services active
systemctl is-active bonbon-safety bonbon-hal bonbon-perception \
  bonbon-speech bonbon-behavior bonbon-navigation bonbon-actuation \
  bonbon-tts bonbon-dashboard bonbon-monitoring
```

## The failure this prevents

Before this work, `systemd_setup.md` told operators to
`systemctl enable bonbon-core bonbon-safety …` — enabling the full-stack
monolith **and** the standalone safety service together, booting two safety
supervisors. Now:

- `Conflicts=bonbon-core.service` on every per-subsystem unit makes systemd
  refuse the combination.
- `validate_boot_topology.py` fails the deploy and prints the exact fix.
- the dashboard shows the blocker under deployment readiness.

See `SAFETY_SUPERVISOR_SINGLETON_POLICY.md` and
`SYSTEMD_DEPLOYMENT_MODES.md`.

## Switching back to monolithic (sim/dev on the same Pi)

```bash
sudo bash scripts/select_deployment_mode.sh monolithic
```
This disables every modular service and enables only `bonbon-core`
(+ dashboard + monitoring) — again exactly one safety supervisor, this time
inside `bonbon-core`.
