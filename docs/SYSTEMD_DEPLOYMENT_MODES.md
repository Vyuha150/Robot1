# Systemd Deployment Modes

BonBon runs in exactly one of two mutually-exclusive systemd modes. Pick one;
the tooling refuses to let you run both (that is the duplicate-safety-
supervisor bug — see `SAFETY_SUPERVISOR_SINGLETON_POLICY.md`).

## Install the units (once)

```bash
sudo cp deployment/systemd/bonbon-*.service /etc/systemd/system/
sudo systemctl daemon-reload
```

## MODE A — Monolithic Bringup (`monolithic`)

`bonbon-core` runs the **complete** stack via `bringup.launch.py`, including
the single safety supervisor. Per-subsystem services stay disabled.

Use for: **simulation, local development, simple lab bring-up.**

```bash
sudo bash scripts/select_deployment_mode.sh monolithic
# equivalently: sudo bash scripts/enable_monolithic_mode.sh
```

Enabled: `bonbon-core`, `bonbon-dashboard`, `bonbon-monitoring`.
Disabled: `bonbon-safety`, `bonbon-hal`, `bonbon-perception`, `bonbon-speech`,
`bonbon-behavior`, `bonbon-navigation`, `bonbon-actuation`, `bonbon-tts`.

## MODE B — Modular Production (`modular_pi`)

The stack is split into independently restartable services. `bonbon-core` is
disabled; `bonbon-safety` is the **single** supervisor. Lets you restart one
subsystem (e.g. perception) without touching safety/navigation.

Use for: **Raspberry Pi production robot, field deployment.**

```bash
sudo bash scripts/select_deployment_mode.sh modular_pi
# equivalently: sudo bash scripts/enable_modular_pi_mode.sh
```

Enabled (started safety + HAL first, then safety-gated subsystems):
`bonbon-safety`, `bonbon-hal`, `bonbon-perception`, `bonbon-speech`,
`bonbon-behavior`, `bonbon-navigation`, `bonbon-actuation`, `bonbon-tts`,
`bonbon-dashboard`, `bonbon-monitoring`.
Disabled: `bonbon-core`.

### Startup ordering in modular mode (enforced by unit `After=`/`Requires=`)

`bonbon-safety` → `bonbon-hal` → (`bonbon-perception`, `bonbon-speech`,
`bonbon-behavior`, `bonbon-navigation`, `bonbon-actuation`, `bonbon-tts`).
Every subsystem `Requires=bonbon-safety` and `After=bonbon-safety bonbon-hal`,
so nothing that can move starts before the safety supervisor is up.

## Validate / inspect at any time

```bash
# static (reads enabled units, writes devops/project-status/boot_topology.json)
python3 scripts/validate_boot_topology.py
# also count live safety supervisors via ros2 node list
python3 scripts/validate_boot_topology.py --check-running-nodes
# runtime duplicate-node check (on the robot, sourced workspace)
bash scripts/check_duplicate_ros_nodes.sh
# one-liner status, no changes
bash scripts/select_deployment_mode.sh status
```

## Mutual exclusion is enforced three ways

1. `Conflicts=bonbon-core.service` on every per-subsystem unit (systemd
   won't co-run them).
2. The enable scripts disable the conflicting set before enabling the chosen
   one.
3. `validate_boot_topology.py` exits non-zero on any mixed/duplicate set.

## Known limitation (honest)

Mode B's `bonbon-perception` brings up `bonbon_perception_ai`; the richer
vision/gesture/affective/speaker enrichment nodes that the monolithic
bringup also starts are **not yet** decomposed into their own modular
services. Modular mode therefore currently runs a *safety-complete* but
*perception-reduced* stack versus monolithic. Adding `bonbon-vision`,
`bonbon-gesture`, etc. as further modular units is a follow-up; it does not
affect the singleton-safety guarantee.
