# Failure and Degraded Mode Policy

**Date:** 2026-07-01
**Scope:** the narrative version of `config/distributed/failure_policy.yaml`
— read that file for the machine-checked values, this document for the
reasoning. Also covers the existing single-machine `SafetyState` degraded
classes (`DEGRADED`, `FAULT`, `SAFE_STOP`), which remain unchanged and are
extended, not replaced, by the distributed layer.

## Two kinds of "degraded" that must not be conflated

1. **Component-level degraded** (already exists): a single module inside a
   Pi fails — e.g. Pi-2's camera driver crashes. Reported today via
   `SafetyState.degraded_modules` and (per Phase 11) a new
   `bonbon_fault_manager` fault-level schema (`OK`/`WARNING`/`DEGRADED`/
   `FAULT`/`CRITICAL`/`BLOCKED`) per component.
2. **Pi-level degraded** (new): an entire Pi becomes unreachable over the
   network. This is not a "fault" of the surviving Pis — it's a topology
   change they must react to. `config/distributed/failure_policy.yaml`
   defines exactly what each surviving Pi does for each possible peer loss.

A single dropped camera frame is (1). A switch cable pulled from Pi-2 is
(2). Both must be visible on the dashboard, but they are different signals
and must not be merged into one generic "something is wrong" indicator —
an operator needs to know whether to check a component or check the network.

## The four Pi-loss scenarios, briefly (full detail in failure_policy.yaml)

| Lost Pi | Observer | Effect on physical safety | Effect on capability |
|---|---|---|---|
| Pi-1 | Pi-3 | **None.** Pi-1 has no motion authority. | No new operator commands can be issued. |
| Pi-2 | Pi-3 | **None.** Motion continues normally. | Human interaction (speech, gesture response) stops; behavior proposals from Pi-2 stop arriving. |
| Pi-3 | Pi-1 | Dashboard must treat motion authority as **unknown**, not "last known good." | All motion-control UI disabled; operator proposals are queued locally, not silently dropped. |
| Pi-3 | Pi-2 | Pi-2 has no authority to lose, so no safety effect. | Pi-2 stops emitting new proposals (nothing to validate them); perception/ASR/LLM keep running locally so recovery is instant on reconnect. |

The pattern across all four: **losing Pi-1 or Pi-2 never touches physical
safety; losing Pi-3 always removes the ability to move, and every other Pi
must say so honestly rather than let cached state look live.**

## Why Pi-3 never depends on Pi-1 or Pi-2 for its own safety loop

This is a design invariant, not an accident: Pi-3's `safety_supervisor_node`
subscribes only to sensors and actuator state that are physically local to
Pi-3 (lidar, IMU, battery, servo state, e-stop) for its **core** safety
classification (`NORMAL`/`CAUTION`/`DANGER`/`FAULT`/`SAFE_STOP`). The one
Pi-2 input it optionally consumes — `/bonbon/human_state/active`, added in
Phase 6 wiring — is an *additional* proximity/intent signal that can only
make the robot **more** cautious (e.g. slow down for a distressed nearby
person), never a signal whose absence removes safety. If Pi-2 disappears,
the supervisor simply stops receiving that extra signal and falls back to
lidar-only proximity detection, which was already sufficient for `CAUTION`/
`DANGER` classification before Pi-2 existed.

## Degraded motion mode (Phase 3/6 — new)

The Phase 1 audit found that today's "degraded mode" concept
(`bonbon_perception_efficiency_node`) only covers *perception* load-
shedding, and that velocity capping in `CAUTION`/`DOCKING` states is a
`SafetyState` side-effect, not a distinct mode. The 3-Pi architecture
introduces one explicit addition: **network-partition-induced degraded
motion**, entered automatically per `pi3_loses_pi2` in
`failure_policy.yaml` — `actuation_permitted` and `navigation_permitted`
stay `true`, but the `degraded_modules` list gains `"human_ai"`, which the
dashboard surfaces distinctly from a hardware `DEGRADED` state so an
operator isn't left wondering whether a sensor failed.

## Recovery behavior

Every failure state in this document is designed to be **self-healing**:
when a lost Pi's heartbeat resumes, the losing Pi's policy reverts
automatically (no manual reset required) — with one deliberate exception:
if the loss coincided with a `SafetyState` transition to `FAULT` or
`SAFE_STOP` for an unrelated reason, that state's own
`requires_manual_reset` flag still applies. Losing and regaining a peer Pi
is never itself a fault condition requiring manual intervention.
