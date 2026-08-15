# 3-Pi Phase 7: Network/Time-Sync/Inter-Pi Reliability

Before writing any code, a read-only audit confirmed most of this phase was
already built by earlier, separate workstreams: `bonbon_distributed_network_monitor`
(chrony clock-offset alerting, 16 tests) and `bonbon_distributed_safety`'s
`HeartbeatMonitor` (peer liveness, 12 tests) were both real, tested, and
deployed. This report covers only the genuine remaining gaps the audit
found.

## What already existed (not rebuilt)

- **Clock time-sync monitoring** — `network_monitor_node.py` parses
  `chronyc tracking` and alerts on offset thresholds.
- **Peer liveness** — `HeartbeatMonitor`'s ONLINE/STALE/LOST state machine,
  consumed by `bonbon_authority_manager`.
- **Deployment automation** — `devops/scripts/bootstrap_pi_network.py`
  (static IP, ROS_DOMAIN_ID, CycloneDDS, chrony) and
  `devops/scripts/check_inter_pi_communication.py` (one-shot diagnostic).
- **Configs/docs** — `config/distributed/robot_network.yaml`,
  `cyclonedds_ethernet_profile.xml`, `INTER_PI_COMMUNICATION_POLICY.md`.

## What was genuinely missing, and what was built

### 1. Continuous network-quality monitoring (the real gap)

Neither chrony nor heartbeat measures link quality directly — a
degraded-but-not-dead link (rising latency, intermittent loss) looked
identical to a fully healthy one on both signals. Added to
`bonbon_distributed_network_monitor`:

- `core/rtt_probe.py`: TCP-connect-timing RTT probe (no raw-socket
  privilege needed), mirroring the technique already proved out in
  `bonbon_benchmarks/three_pi_network_benchmark.py` for one-shot
  benchmarking — this is the continuously-polled production counterpart.
- `core/quality_evaluator.py`: pure metrics + trigger evaluation, same
  shape as the existing `offset_evaluator.py`. RTT and packet loss are
  evaluated independently (a link can be lossy-but-fast or slow-but-
  reliable; conflating them would hide which dimension degraded).
- `core/network_thresholds.py` gained `NetworkQualityThresholds` and
  `load_peer_targets()`, reading a new `network_quality` section in
  `robot_network.yaml` (probe port 22 — SSH, the one TCP service
  guaranteed listening on every deployed Pi, used only for reachability
  timing, never an actual session).
- `network_monitor_node.py` now probes every other Pi on the same tick it
  checks its own clock, publishes `HalFault` on breach (same existing
  `/bonbon/hal/fault` ingestion path, no second alerting mechanism), and
  extends its `/bonbon/network_monitor/status` JSON with per-peer
  `peer_link_quality`.
- **20 new tests** (`test_rtt_probe.py`, `test_quality_evaluator.py`, plus
  additions to `test_network_thresholds.py`).

### 2. Link-flap detection (`bonbon_distributed_safety`)

`HeartbeatMonitor.evaluate()` reports discrete state transitions but
nothing tracked transition *rate* — a peer flapping ONLINE↔STALE
repeatedly looked the same as one that transitioned once and stayed put.
Added `core/flap_detector.py` (`FlapDetector`, sliding-window transition
count per peer) and wired it into `distributed_safety_node.py`'s
`_cb_evaluate`: a peer crossing the flap threshold (default: 3 transitions
in 60s) now publishes a distinct `pi_link_flapping` `SafetyEvent`,
separate from the existing per-transition event. **10 new tests**.

### 3. Test coverage for the two previously-untested devops scripts

`bootstrap_pi_network.py` and `check_inter_pi_communication.py` had zero
test coverage anywhere in the repo (confirmed by grep). Added
`devops/tests/test_network_scripts.py`: pure-helper tests
(`_load_network_config`, `_upsert_env_file`, `_check_domain_id`,
`_check_topic_advertised`) plus real subprocess invocations of both
scripts' safe paths — `bootstrap_pi_network.py`'s dry-run mode (never
touches the real system without `--apply`, which requires root and is
correctly not exercised here) and `check_inter_pi_communication.py`'s
read-only checks (which honestly report FAIL/exit-1 in this sandbox,
since the configured peer IPs are unreachable and `ros2` isn't on PATH —
that failure IS the behavior under test: it must fail loudly, never a
fabricated PASS). **18 new tests.**

### 4. Doc drift fix

`cyclonedds_ethernet_profile.xml`'s header referenced
`scripts/bootstrap_pi_network.sh`; the real file is
`devops/scripts/bootstrap_pi_network.py`. Corrected.

## Regression

| Suite | Result |
|---|---|
| `bonbon_distributed_network_monitor` (repo-root `tests/`) | 38/38 passed |
| `bonbon_distributed_safety` (core, non-integration) | 28/28 passed |
| `devops/tests` (new file only) | 18/18 passed |

**4 pre-existing, unrelated failures** were found in `devops/tests` during
this pass (`test_integration_test_execution_in_ci`,
`test_missing_environment_variable_fails_for_lab_robot`,
`test_dockerfiles_run_as_non_root_after_build`,
`test_ci_workflow_contains_required_pipeline_stages`) — confirmed via
`git stash` to predate this session's changes entirely, not introduced by
this pass. Left untouched: out of scope for a network/time-sync task, and
fixing them without understanding their full original context risks
masking a real finding from whichever pass created them.

## Not done (deliberately out of scope)

- No fully-online continuous packet-capture/jitter analysis — the RTT
  probe's `packet_loss_pct` (successful/attempted TCP connects per check)
  is the honest proxy chosen; true ICMP-style jitter would need raw-socket
  privilege this deployment doesn't grant.
- `--apply` path of `bootstrap_pi_network.py` is untested — requires root
  and real `nmcli`/`chrony`/`hostnamectl`, none of which belong in a unit
  test; `os.geteuid()` is POSIX-only so this script cannot even be
  imported for that path on a Windows dev box.
- Real-hardware validation of the new RTT thresholds (`rtt_warn_ms=50`,
  `rtt_alert_ms=200`) — untuned defaults, same honesty caveat as every
  other threshold introduced in this pass; needs a real 3-Pi network run.
