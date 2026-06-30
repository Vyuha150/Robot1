# Duplicate Pipeline Risk Report (Phase 1 — read-only)

**Date:** 2026-06-30
**Scope:** Deployment requirement #10 — *no duplicate camera/audio/database/
safety pipelines.*

## The defect

`bonbon-core` runs `bringup.launch.py`, which starts a **complete** stack —
including a `safety_supervisor_node`, the perception_ai nodes, the speech
nodes, the tts node, and the navigation nodes. The systemd set *also* ships
standalone `bonbon-safety`, `bonbon-perception`, `bonbon-speech`,
`bonbon-tts`, and `bonbon-navigation` services that start those **same**
subsystems again. `systemd_setup.md` instructs enabling `bonbon-core`
**and** `bonbon-safety` together, and its start-order text implies the
per-subsystem services too.

## What actually breaks when both are enabled

Every node in BonBon is created with a **fixed node name** (e.g.
`safety_supervisor_node`, set in each node's constructor — not auto-suffixed).
Running two copies therefore produces, per duplicated subsystem:

1. **Two ROS2 nodes with the same fully-qualified name.** ROS2 does not
   reject this; it logs a warning and continues with undefined behaviour —
   service names collide, parameter sets collide, and `ros2 node list` shows
   the name once while two processes back it.
2. **Two publishers on the same topic.** For `safety_supervisor_node` this
   means two publishers on `/bonbon/safety/state`, which is
   `RELIABLE`/`TRANSIENT_LOCAL`. Subscribers (the dashboard bridge,
   behavior engine, actuation gate, navigation) receive whichever publisher's
   sample is latest — **nondeterministically**. If the two supervisors ever
   disagree (e.g. one sees a fault the other hasn't processed yet), a
   consumer can act on the *wrong* safety state. This is the single most
   dangerous consequence and the reason this is a deployment **blocker**, not
   a warning.
3. **Duplicate sensor consumers.** Two perception pipelines both subscribe to
   the camera/person topics and both run inference — doubling CPU/NPU load on
   a Pi that is already the tightest-budget target, directly working against
   requirements #5/#7/#8.
4. **Duplicate database writers.** Two `core`/perception stacks both opening
   the SQLite data store (mounted at the same `/var/lib/bonbon` path) risks
   `database is locked` contention and double-counted analytics.

## Severity by pipeline

| Pipeline | Duplicated by | Severity | Why |
|---|---|---|---|
| Safety supervisor | core + bonbon-safety | **Blocker** | Two `/bonbon/safety/state` publishers → nondeterministic safety state |
| Perception (vision/AI) | core + bonbon-perception | High | Double inference load on the Pi; duplicate person/object topics |
| Speech | core + bonbon-speech | High | Two mic consumers; duplicate STT |
| TTS | core + bonbon-tts | Medium | Two speakers racing the audio device |
| Navigation | core + bonbon-navigation | High | Two nav stacks issuing motion goals |
| Database | core + perception | Medium | SQLite lock contention |

## ROS2-graph vs deployment distinction (important)

In a *single correctly-launched* stack the ROS2 graph is clean — there is
exactly one of each node, no duplicate pipelines. The defect lives **entirely
in the systemd/compose deployment layer**: it's the *enablement of two stacks
at once* that creates duplicates, not anything in the node code. This is why
Phase 2's fix is a deployment-topology guard, not a change to any node.

## Why it wasn't caught earlier

- Pure-Python and even colcon CI run one launch at a time; they never enable
  two systemd services together, so the duplication is structurally invisible
  to the existing test suites.
- On a desktop the duplication "works" (just wasteful + noisy warnings); the
  nondeterministic-safety-state consequence only bites under real divergence,
  which is rare and timing-dependent — the worst kind of latent bug.

## Required outcome (implemented in Phase 2)

Exactly **one** active `safety_supervisor_node` in every runtime mode,
enforced by a validator that fails deployment if `bonbon-core` and any
modular service are enabled together, plus a runtime duplicate-node check.
