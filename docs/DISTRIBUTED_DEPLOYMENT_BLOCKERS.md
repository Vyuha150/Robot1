# Distributed Deployment Blockers (Three-Pi Split)

**Date:** 2026-07-01
**Scope:** Everything that stops the repo from running as three physically
separate Raspberry Pi 5 boards today, ranked by whether it blocks deployment
outright or degrades it. Read-only audit — no code changed to produce this
report.

Companion docs: `THREE_PI_CURRENT_ARCHITECTURE_AUDIT.md` (narrative),
`COMPONENT_SUPPORT_MATRIX.md` (table), `HARDWARE_SOFTWARE_GAP_REPORT.md`
(missing drivers), `DUPLICATE_PIPELINE_RISK_REPORT.md` (duplication risk).

## BLOCKER 1: No ROS2 multi-machine networking configuration exists

**Finding:** Full-repo grep for `ROS_DOMAIN_ID`, DDS profile XML, FastRTPS/
CycloneDDS configuration returns **zero matches**. Every launch file,
systemd unit, and script assumes ROS2's default same-machine DDS discovery
over loopback.

**Why it blocks deployment:** Split across three physical Pis on Ethernet,
ROS2 nodes on different machines will not discover each other at all unless
they share a `ROS_DOMAIN_ID` and DDS multicast/unicast discovery actually
reaches across the wire — which depends on network config (switch multicast
support, firewall rules) that isn't yet decided or documented.

**Resolution path (Phase 2/7 of this brief):** static IP plan (already
specified: 192.168.10.11/12/13), shared `ROS_DOMAIN_ID` exported by every
Pi's systemd environment file, a CycloneDDS (or FastRTPS) profile tuned for
Ethernet reliability, and a runtime discovery-health check
(`bonbon_distributed_network_monitor`, Phase 7).

## BLOCKER 2: No per-Pi launch files — only monolithic and single-machine-modular

**Finding:** `bringup.launch.py` (222 lines) launches the entire stack —
safety, HAL, vision, speech, the 8-node AI reasoning group, behavior engine,
actuation, navigation, TTS, operator API — in one process tree. The
"modular" per-subsystem launch files (`safety.launch.py`, `vision.launch.py`,
etc.) exist for **systemd service granularity on one Pi**, not for grouping
by which physical Pi a component belongs on. There is no `pi1_bringup.
launch.py` / `pi2_bringup.launch.py` / `pi3_bringup.launch.py` that launches
exactly and only the nodes for that Pi's role.

**Why it blocks deployment:** Without per-Pi launch files, there's no single
command to bring up "everything Pi-2 needs and nothing else" — an operator
would have to manually assemble the correct subset of existing
per-subsystem launch files per machine, with no validation that the subset
is complete or non-overlapping.

**Resolution path (Phase 2 of this brief):** three new launch files, one per
Pi, each including only the already-correctly-scoped per-subsystem launch
files for that Pi's role (this is mostly composition of existing pieces, not
new node code).

## BLOCKER 3: Dashboard bridge hardcodes topic names with an implicit localhost assumption

**Finding:** `bonbon_operator_api/ros2/ros2_bridge.py:73-104` defines fixed
topic-name constants (`/bonbon/safety/state`, `/navigation/status`,
`/bonbon/persons/tracks`, etc.) and subscribes to them via the local ROS2
node's default DDS participant. This works today because everything runs on
one machine. It has no explicit assumption *documented* that breaks it for
multi-machine — the topic names themselves are fine — but it has never been
tested or configured to discover topics published by nodes on a different
machine's DDS domain.

**Why it blocks deployment:** Once Pi-2 and Pi-3 nodes exist only on their
own machines, Pi-1's dashboard bridge will show every remote topic as
silently unavailable unless Blocker 1's networking fix is in place *and* the
bridge's timeouts/reconnect logic are verified against real network latency
(not just process-local pub/sub, which has near-zero latency).

**Resolution path (Phase 2/4 of this brief):** no topic-name changes needed;
requires Blocker 1's fix plus explicit heartbeat-loss handling in the
dashboard (already scoped in the brief's Phase 3 authority rules: "Pi-1 loses
Pi-3 → dashboard shows motion authority unavailable").

## BLOCKER 4 (CRITICAL, cross-referenced from HARDWARE_SOFTWARE_GAP_REPORT.md): Pi-3 cannot drive the base

**Finding:** No Cytron MDDS30 / Rhino motor driver exists (see gap report
item 1). Nav2 can plan; the safety gate can approve a velocity command; no
software converts that into physical wheel motion.

**Why it blocks deployment:** This blocks the *entire navigation capability*
of the robot, independent of the 3-Pi split — it would block a single-Pi
deployment equally. Listed here because Phase 6 of this brief explicitly
requires it to complete Pi-3.

**Resolution path:** new `bonbon_motor_cytron_mdds30` + `bonbon_base_
controller` packages (Phase 6).

## BLOCKER 5: Safety Supervisor does not yet consume Pi-2's gesture/human-state topics

**Finding:** `safety_supervisor_node.py`'s subscriber set (14 topics) covers
lidar, IMU, battery, temperature, servo state, `/bonbon/vision/persons`
(proximity), e-stop, and module health — but not `/bonbon/gesture/events`
or `/bonbon/human/state`, both of which are published today by Pi-2-role
packages (`bonbon_gesture`, `bonbon_human_state_fusion`). This was already
flagged in the single-machine Perception AI audit and remains true.

**Why it matters for the 3-Pi split specifically:** the brief's Phase 3
safety/authority model requires Pi-2's *proposals* (which should be informed
by gesture/human-state context, e.g. a `go_away` gesture or a distress
emotional state) to reach Pi-3's safety validation. Today that channel
doesn't exist even locally, so it certainly doesn't exist across the network
boundary yet.

**Resolution path (Phase 3/6 of this brief):** wire the new
`/bonbon/behavior/proposal` topic (Phase 3) to carry this context from Pi-2
to Pi-3, and/or add the direct subscriptions to the safety supervisor as a
defense-in-depth signal.

## BLOCKER 6: `config/pi_efficiency_profile.yaml` is a single unscoped priority list

**Finding:** The existing efficiency profile lists load-shedding priority
for all ~18 modules assuming they coexist on one Pi (confirmed in the
Finalization Mode brief's Phase 4). It has no per-role subset.

**Why it blocks correct behavior post-split:** Pi-1 would try to reason
about shedding perception/LLM load it doesn't run; Pi-3 would never shed
perception load because it has none, but also has no profile entry for its
actual navigation/motor-control priorities.

**Resolution path (Phase 2/7 of this brief):** `config/distributed/
pi_ui_api.yaml`, `pi_human_ai.yaml`, `pi_navigation_safety.yaml` runtime
profiles, each scoped to that Pi's actual module set — likely superseding
(not just supplementing) the single-file profile for 3-Pi deployments while
the single-file profile remains valid for single-machine dev/lab mode.

## Non-blockers worth naming (already correct, do not need rework)

- **Duplicate safety supervisor**: resolved and verified still intact
  (systemd `Conflicts=`, `boot_topology.py`, `check_duplicate_ros_nodes.sh`).
- **Duplicate camera/mic pipelines**: none exist; single device-owner
  pattern confirmed clean.
- **LLM/dashboard cannot reach motor topics**: verified true by tracing
  every publisher of `/cmd_vel`-equivalent and servo-command topics; only
  `safety_gate_node.py` publishes them.
- **Local-only LLM**: `ollama_client.py` has no cloud-API code path.

## Priority order for closing blockers (recommended, not yet executed)

1. Blocker 4 (drive motors) — without this, navigation cannot function
   regardless of network topology; highest physical-capability impact.
2. Blocker 1 (ROS_DOMAIN_ID/DDS) — without this, nothing on separate Pis can
   talk to anything else at all; highest architectural-capability impact.
3. Blocker 2 (per-Pi launch files) — mechanical composition once Blocker 1
   is decided.
4. Blocker 3 (dashboard cross-machine reachability) — verification/hardening
   once 1 and 2 exist.
5. Blocker 5 (safety consuming gesture/human-state) — correctness hardening,
   not a hard blocker to first boot.
6. Blocker 6 (per-Pi efficiency profiles) — optimization, not a hard blocker
   to first boot.
