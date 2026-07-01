# bonbon_distributed_safety

Cross-Pi liveness tracking for the three-Pi deployment
(`docs/FINAL_THREE_PI_ARCHITECTURE.md`). Publishes this Pi's own
`/bonbon/pi{N}/heartbeat` unconditionally and tracks the other two Pis'
via `HeartbeatMonitor`, emitting `/bonbon/system/failure_events` on every
ONLINE/STALE/LOST transition.

Runs on all three Pis (`self_id` ROS2 param: `pi1`|`pi2`|`pi3`). Does not
decide *behavior* on peer loss — that's `bonbon_authority_manager`'s job,
consuming this package's link-state output.

## What it does NOT do

It does not gate proposals, does not decide degraded mode, and does not
know anything about `failure_policy.yaml`'s per-scenario behaviors — those
live in `bonbon_authority_manager`, kept separate so "detect a peer is
gone" and "decide what to do about it" can be tested and reasoned about
independently.

## Core logic (fully unit-tested, no rclpy dependency)

`core/heartbeat_monitor.py` — `HeartbeatMonitor`. A peer that has never
sent a heartbeat is `LOST`, never assumed `ONLINE` — see
`docs/HARDWARE_SOFTWARE_GAP_REPORT.md`'s and this repo's broader
no-fake-PASS posture. 12 tests in `tests/test_heartbeat_monitor.py`.
