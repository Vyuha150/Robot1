# Safety Supervisor Singleton Policy

**Invariant:** In every runtime mode, on every machine, there must be
**exactly one** running `safety_supervisor_node`.

## Why

`safety_supervisor_node` publishes `/bonbon/safety/state` with
`RELIABLE` + `TRANSIENT_LOCAL` QoS. Every actuation/navigation/behavior/
dashboard consumer trusts that topic as the single source of safety truth.
Two supervisors means two publishers on that topic: a late-joining or
reconnecting subscriber receives whichever publisher's sample arrived last,
**nondeterministically**. If the two ever disagree — one has processed a
fault the other hasn't — a consumer can act on a *stale, unsafe* state. A
robot that can move must never be in that situation.

It is also a plain ROS2 fault: both processes register the **same** node
name (`safety_supervisor_node`, fixed in the constructor, not auto-suffixed),
so service names, parameters, and lifecycle transitions collide.

## How the invariant is enforced (defence in depth)

1. **systemd `Conflicts=`** — every per-subsystem unit
   (`bonbon-safety`, `bonbon-hal`, `bonbon-perception`, `bonbon-speech`,
   `bonbon-behavior`, `bonbon-navigation`, `bonbon-actuation`, `bonbon-tts`)
   declares `Conflicts=bonbon-core.service`. systemd will refuse to run the
   standalone safety/subsystem services at the same time as the monolithic
   `bonbon-core` (which contains its own supervisor) — starting one stops
   the other. This makes the duplicate impossible to *boot*.
2. **Mode-selection scripts** — `enable_monolithic_mode.sh` /
   `enable_modular_pi_mode.sh` always *disable the conflicting set first*,
   then enable the chosen set, then validate. There is no path through them
   that leaves both enabled.
3. **Static validator** — `scripts/validate_boot_topology.py` reads the
   enabled-unit set and **fails (exit 1)** on any duplicate or missing
   supervisor, writing the verdict to
   `devops/project-status/boot_topology.json`.
4. **Runtime validator** — `scripts/check_duplicate_ros_nodes.sh` counts
   live `safety_supervisor_node` processes via `ros2 node list` and fails if
   the count is not exactly 1.
5. **Dashboard** — surfaces the boot-topology verdict (mode, duplicate
   flag, remediation command) so an operator sees the blocker, and rolls it
   into deployment-readiness.

## What this policy does NOT change

The Safety Supervisor's **internal logic is untouched** — its state machine,
fault catalogue, e-stop handling, and thresholds are exactly as before. This
policy is entirely about the *deployment topology around* the supervisor:
ensuring one, and only one, instance runs.

## The two valid modes

| | Monolithic (Mode A) | Modular Pi (Mode B) |
|---|---|---|
| Who runs the supervisor | inside `bonbon-core` (full bringup) | standalone `bonbon-safety` |
| `bonbon-core` | enabled | **disabled** |
| per-subsystem services | **disabled** | enabled |
| Used for | sim / dev / lab | Raspberry Pi production |

Any other combination is **invalid** and rejected. See
`SYSTEMD_DEPLOYMENT_MODES.md` and `PI_BOOT_TOPOLOGY.md`.
