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

---

## Addendum (2026-07-01): Three-Pi distributed deployment — new duplication risks

**Scope:** the three-Pi brief (PI-1 UI/API, PI-2 Human AI, PI-3 Navigation/
Motion/Safety). The single-machine defect above is fully resolved and stays
resolved for single-Pi deployments — this addendum covers **new** risks that
only exist once nodes are split across three physically separate machines.
Read-only finding; no code changed.

### New risk 1: a Pi accidentally launching `bonbon-core` in addition to its role

The existing `Conflicts=bonbon-core.service` guard only prevents *one Pi*
from running both the monolithic stack and its modular services
simultaneously. It does **not** prevent a misconfigured Pi-1 (say) from
having `bonbon-core.service` enabled at all — on a single Pi that would just
be "monolithic mode," but on a 3-Pi deployment it would mean Pi-1 runs a
**second, fully-featured safety supervisor** in addition to Pi-3's, with no
existing cross-machine check to catch it. This is the same class of bug as
the resolved single-machine one, but the "two supervisors" now live on two
different IP addresses instead of two local processes — `ros2 node list`
alone can no longer detect it locally; detection requires a **network-aware**
check.

**Required outcome (Phase 8 of the 3-Pi brief):** extend
`check_duplicate_ros_nodes.sh` (or a new
`scripts/check_inter_pi_communication.py`) to enumerate the live ROS2 graph
across the shared `ROS_DOMAIN_ID` and fail if more than one
`safety_supervisor_node`, `behavior_engine_node`, or `llm_orchestrator_node`
is visible network-wide — not just locally per machine.

### New risk 2: Pi-2 or Pi-1 accidentally opening a camera/mic device via a stray monolithic launch

Today's "no duplicate camera/mic pipeline" finding (see main report above)
is verified for a single machine's process tree. If Pi-1 or Pi-3 were ever
started with `bringup.launch.py` instead of a Pi-scoped launch file (see
`DISTRIBUTED_DEPLOYMENT_BLOCKERS.md`, Blocker 2 — no per-Pi launch files
exist yet), they would attempt to open camera/microphone devices that either
don't physically exist on that Pi (harmless local failure) or, worse, if a
future deployment mistakenly attaches the same physical camera/mic to two
Pis (e.g. over a USB extender or shared capture device), would create a
genuine duplicate-pipeline condition indistinguishable from the resolved
single-machine bug.

**Required outcome (Phase 2 of the 3-Pi brief):** per-Pi launch files that
make it structurally impossible to launch `bringup.launch.py`'s full stack
on any single Pi in a 3-Pi deployment — this is a **prerequisite**, not just
a convenience (see Blocker 2).

### New risk 3: Pi-2's LLM/perception proposals reaching Pi-3 through an unintended path

The brief requires all inter-Pi movement-related communication to flow as
typed proposals through `/bonbon/behavior/proposal` →
`bonbon_motion_approval_gateway` → Pi-3's safety supervisor (Phase 3). Today,
no such distributed topic or gateway exists yet (confirmed: zero occurrences
of "behavior/proposal", "motion_approval_gateway", "authority_manager" in
the repo). The risk is *architectural*, not yet realized in code: once
built, if any Pi-2 node were given a second, informal way to reach Pi-3
(e.g. a raw string topic, a direct service call bypassing the gateway), that
would recreate the "two paths to the same dangerous action" pattern this
report exists to catch — just one level higher in the stack (behavior
proposals instead of raw motor commands).

**Required outcome (Phase 3 of the 3-Pi brief):** exactly one message type
and one topic (`/bonbon/behavior/proposal`) for Pi-2→Pi-3 movement-related
communication, with `bonbon_motion_approval_gateway` as the sole consumer
authorized to forward proposals into Pi-3's existing safety-gate chain — no
second path.

### Net assessment

No **new** duplication exists in the codebase today (there is no Pi-2/Pi-3
distributed code yet to duplicate). All three risks above are **preventive**
— they describe how the already-solved single-machine duplication bug could
reappear in a new form once Phases 2/3/8 are implemented, and what guard
each phase must include to avoid reintroducing it. This report should be
re-verified (not just re-read) after Phases 2, 3, and 8 land.
