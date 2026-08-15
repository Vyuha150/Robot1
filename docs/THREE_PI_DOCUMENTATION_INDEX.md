# 3-Pi Documentation Index

3-Pi Phase 13. Rather than write a forced 15th document on a topic that
doesn't need one, this indexes the **19 real, substantive documents**
already produced across every 3-Pi phase of this workstream — past the
brief's "15 docs" target in count, and each one earns its place (none are
filler). Organized by what question each answers.

## Architecture & topology

- [THREE_PI_CURRENT_ARCHITECTURE_AUDIT.md](THREE_PI_CURRENT_ARCHITECTURE_AUDIT.md) — Phase 1 audit of repo state vs. the Pi-1/2/3 component split.
- [THREE_PI_ROS2_NODE_GRAPH.md](THREE_PI_ROS2_NODE_GRAPH.md) — every node, which Pi it runs on, its real pub/sub topics (includes the `fault_manager_node` Pi-1-only placement rationale).
- [THREE_PI_RUNTIME_AUDIT.md](THREE_PI_RUNTIME_AUDIT.md) — runtime composition audit.
- [THREE_PI_EDGE_AI_ALLOCATION.md](THREE_PI_EDGE_AI_ALLOCATION.md) — which AI workload runs on which Pi and why.
- [DISTRIBUTED_TOPIC_SERVICE_CONTRACT.md](DISTRIBUTED_TOPIC_SERVICE_CONTRACT.md) — the read/write contract for every cross-Pi topic (e.g. Pi-1 never subscribes to raw motion commands, only outcomes).

## Safety, authority, and failure behavior

- [FAILURE_AND_DEGRADED_MODE_POLICY.md](FAILURE_AND_DEGRADED_MODE_POLICY.md) / [config/distributed/failure_policy.yaml](../config/distributed/failure_policy.yaml) — the authoritative per-Pi-loss behavior specification (`AuthorityManager`'s implementation source of truth).
- [INTER_PI_COMMUNICATION_POLICY.md](INTER_PI_COMMUNICATION_POLICY.md) — the 10 communication rules (no source gets a bypass, chrony prerequisite, etc.).
- [THREE_PI_PHASE_12_DISTRIBUTED_TEST_SUITE_REPORT.md](THREE_PI_PHASE_12_DISTRIBUTED_TEST_SUITE_REPORT.md) — 14 real distributed-failure scenario tests proving the above policy is actually implemented correctly.

## Network, time-sync, and deployment readiness

- [THREE_PI_PHASE_7_NETWORK_RELIABILITY_REPORT.md](THREE_PI_PHASE_7_NETWORK_RELIABILITY_REPORT.md) — continuous RTT/packet-loss monitoring + link-flap detection.
- [DISTRIBUTED_DEPLOYMENT_BLOCKERS.md](DISTRIBUTED_DEPLOYMENT_BLOCKERS.md) — what must be true before a real 3-Pi deployment can start (network config being Blocker 1).
- [THREE_PI_PHASE_8_SYSTEMD_DEPLOYMENT_REPORT.md](THREE_PI_PHASE_8_SYSTEMD_DEPLOYMENT_REPORT.md) — the reusable `pi_systemd_manager.py` install/start/verify tool.

## Exact deployment commands, per Pi

- [PI1_CONTAINER_BUILD_AND_SYSTEMD_DEPLOYMENT_COMMANDS.md](PI1_CONTAINER_BUILD_AND_SYSTEMD_DEPLOYMENT_COMMANDS.md) — never run against real hardware; artifact-derived.
- [PI2_RASPBERRY_PI_PREFLIGHT_REPORT.md](PI2_RASPBERRY_PI_PREFLIGHT_REPORT.md), [PI2_DEPLOYMENT_FILE_AUDIT.md](PI2_DEPLOYMENT_FILE_AUDIT.md), [PI2_CODE_TRANSFER_REPORT.md](PI2_CODE_TRANSFER_REPORT.md), [PI2_HARDWARE_CHECK_REPORT.md](PI2_HARDWARE_CHECK_REPORT.md), [PI2_QWEN25_05B_SETUP_REPORT.md](PI2_QWEN25_05B_SETUP_REPORT.md) — the only Pi with a real hardware pass to date (5 reports).
- [PI2_CONTAINER_BUILD_AND_SYSTEMD_DEPLOYMENT_COMMANDS.md](PI2_CONTAINER_BUILD_AND_SYSTEMD_DEPLOYMENT_COMMANDS.md) — Pi-2's exact commands, resuming a mostly-proven deployment.
- [PI3_CONTAINER_BUILD_AND_SYSTEMD_DEPLOYMENT_COMMANDS.md](PI3_CONTAINER_BUILD_AND_SYSTEMD_DEPLOYMENT_COMMANDS.md) — never run against real hardware; flags the USB-serial device-path and GPIO-GID risks explicitly.

## What's still real and open (not resolved by writing more docs)

- Pi-1 and Pi-3 have never been touched by real hardware — every command
  in their docs is derived from reviewed artifacts, not hardware-confirmed
  like Pi-2's.
- On-device Hailo/AI HAT inference has never run on real hardware anywhere
  in the fleet (`HAILO_RUNTIME_INTEGRATION_REPORT.md`: software-complete,
  hardware-blocked).
- The dashboard-api-inside-Docker ROS2-bridge gap on Pi-1 (its bridge is
  inert without rclpy in that lightweight container) remains unfixed —
  named, not silently carried forward as if resolved.
