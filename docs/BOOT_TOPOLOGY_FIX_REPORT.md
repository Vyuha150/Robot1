# Boot Topology Fix Report (Phase 2)

**Blocker:** the documented systemd setup enabled `bonbon-core` (full
`bringup.launch.py`, including a safety supervisor) *together with* the
standalone `bonbon-safety` (and other per-subsystem) services — booting two
`safety_supervisor_node` processes, two publishers on the transient-local
`/bonbon/safety/state`, i.e. nondeterministic safety state. Violated
requirement #10.

## Status: FIXED (and tested without a Pi)

Exactly one safety supervisor in every mode, enforced four ways:

1. **systemd `Conflicts=bonbon-core.service`** on all 8 per-subsystem units
   (safety, hal, perception, speech, behavior, navigation, actuation, tts) —
   systemd refuses to co-run them with the monolith. Navigation/actuation
   also `Requires=bonbon-safety` (+ hal); nothing that moves starts before
   safety.
2. **Mode scripts** (`select_deployment_mode.sh {monolithic|modular_pi|status}`,
   `enable_monolithic_mode.sh`, `enable_modular_pi_mode.sh`) disable the
   conflicting set *before* enabling the chosen one, then validate.
3. **Static validator** `scripts/validate_boot_topology.py` →
   `devops/scripts/boot_topology.py` classifier: reads enabled units (+
   optional live `ros2 node list` count), exits non-zero on duplicate/missing
   safety, writes `devops/project-status/boot_topology.json`.
4. **Runtime guard** `scripts/check_duplicate_ros_nodes.sh` — fails if
   `ros2 node list` shows ≠ 1 `safety_supervisor_node`.

Added the missing modular units (`bonbon-hal`, `bonbon-behavior`,
`bonbon-actuation`) + compose services that the modular mode needs.

## Two modes

- **Monolithic (A):** `bonbon-core` runs everything; per-subsystem services
  disabled. Sim / dev / lab.
- **Modular Pi (B):** per-subsystem services; `bonbon-core` disabled;
  `bonbon-safety` is the single supervisor. Pi production.

## Tests (12, all pass, no Pi)

`devops/tests/test_boot_topology.py`: monolithic-valid, modular-valid,
mixed-invalid, duplicate-safety-fails, duplicate-perception-flagged,
dashboard-serialisation, remediation generation/refs, runtime observed-count
override (2 supervisors → invalid; 0 → invalid), no-safety-anywhere,
`.service`-suffix normalisation. Plus the updated systemd-ordering
integration test asserting `Conflicts=bonbon-core` on every modular unit.

## Honest residual

Modular mode currently brings up `bonbon_perception_ai` for perception but
not yet the finer vision/gesture/affective/speaker enrichment nodes as their
own services (they still come up inside monolithic `bonbon-core`). That's a
capability-decomposition follow-up; it does **not** affect the
single-safety-supervisor guarantee. Confirming the live boot on a real Pi
(`systemctl is-active …`, `ros2 node list`) is the BLOCKED row in the final
checklist.

Docs: PI_BOOT_TOPOLOGY.md, SYSTEMD_DEPLOYMENT_MODES.md,
SAFETY_SUPERVISOR_SINGLETON_POLICY.md.
