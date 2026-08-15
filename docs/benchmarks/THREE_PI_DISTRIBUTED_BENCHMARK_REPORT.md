# Three-Pi Distributed Benchmark Report

**Run:** real, from `docs/project-status/efficiency_benchmark_results.json`'s `three_pi_network` category + `tests/benchmarks/test_three_pi_distributed_benchmark.py` (9 tests). This is a single-machine dev environment -- real hardware tests are marked `HARDWARE_BLOCKED` per the brief's explicit instruction, not simulated with a fabricated number.

## The 10 required measurements

| # | Measurement | Result |
|---|---|---|
| 1 | UI Pi heartbeat | HARDWARE_BLOCKED -- needs real `bonbon_distributed_safety`/`bonbon_authority_manager` ROS2 nodes |
| 2 | AI Pi heartbeat | HARDWARE_BLOCKED -- same reason |
| 3 | Navigation Pi heartbeat | HARDWARE_BLOCKED -- same reason |
| 4 | Network latency UI <-> AI | HARDWARE_BLOCKED -- `bonbon-pi1.local:8000` unreachable (real TCP-connect-RTT probe, honestly failed after 1 bounded attempt, not retried 20x pointlessly) |
| 5 | Network latency AI <-> Nav | HARDWARE_BLOCKED -- `bonbon-pi2.local:8000` unreachable |
| 6 | Network latency UI <-> Nav | HARDWARE_BLOCKED -- `bonbon-pi3.local:8000` unreachable |
| 7 | Behavior proposal latency | HARDWARE_BLOCKED -- needs a real AI-Pi -> Nav-Pi ROS2 service/topic crossing; an in-process function call would not exercise the real cross-machine path |
| 8 | Navigation approval latency | HARDWARE_BLOCKED -- same reason |
| 9 | Dashboard aggregation latency | **PASS**, real -- this measurement genuinely doesn't need a real multi-Pi network (the UI Pi aggregates whatever distributed snapshot it currently has); measured via `GET /api/v1/status`, p95=12.7ms |
| 10 | Degraded mode trigger on Pi failure | HARDWARE_BLOCKED -- requires a real Pi to actually stop responding; cannot be honestly simulated in a single-process test |

## Probe mechanism validation

The TCP-connect-RTT probe itself is proven correct against a real loopback listener (not a mock): `p95=23.8ms` round-trip to a real socket server on `127.0.0.1`, explicitly labeled "LOOPBACK SELF-TEST ONLY -- NOT representative of real inter-Pi network latency." This distinguishes "the measurement tool works" from "the measurement is representative," which the brief's own honesty requirements demand kept separate.

## Confirmed gap this pass closed

Before this pass, no inter-Pi network latency/RTT measurement existed anywhere in the repository (`bonbon_distributed_network_monitor` only measures clock offset via chrony). `bonbon_benchmarks/three_pi_network_benchmark.py` is the first such probe, with bounded DNS resolution (a naive `socket.create_connection()` call would otherwise hang for the OS's full mDNS resolver timeout on an unresolvable `.local` hostname -- caught and fixed during this pass's own testing, not left as a landmine).

## Verdict: **HARDWARE_BLOCKED** for 9/10 measurements (genuinely requires real multi-Pi hardware); **PASS** for the one measurement that doesn't. Run `bash scripts/benchmarks/run_hardware_benchmarks.sh` from each real Pi against the other two once deployed.
