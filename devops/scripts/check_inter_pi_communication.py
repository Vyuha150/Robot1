#!/usr/bin/env python3
"""Verify the three-Pi robot's inter-Pi communication is ACTUALLY working
-- not just "no duplicate nodes" (scripts/check_duplicate_ros_nodes.sh
checks that already, and does so network-aware automatically since
`ros2 node list` queries the whole shared DDS domain, not just the
local process). This script answers a different, positive question:
can this Pi actually SEE and RECEIVE DATA from the other two, right now?

A misconfigured ROS_DOMAIN_ID, a CycloneDDS unicast peer list missing an
IP, or a firewall blocking DDS traffic all produce the exact same
symptom: each Pi runs fine in isolation, `check_duplicate_ros_nodes.sh`
reports "clean" (vacuously -- there's nothing to duplicate against if
you can't see the other Pis at all), and the robot silently never
discovers the failure until an operator notices navigation isn't
responding to a safety block, or the dashboard shows every Pi as
offline. This script is the explicit, positive confirmation step that
closes that gap.

Checks, in order (fails fast on the earliest, cheapest check that can
explain a downstream failure):
  1. ROS_DOMAIN_ID matches robot_network.yaml (the #1 cause of "Pis
     can't see each other" is simply forgetting to export it).
  2. L3 reachability: `ping` each peer's static IP. Distinguishes
     "network is down" from "DDS discovery is misconfigured" -- very
     different remediations.
  3. DDS-level discovery: each peer's heartbeat topic appears in
     `ros2 topic list`.
  4. Live data: each peer's heartbeat topic is actually publishing
     (bounded-time `ros2 topic echo --once`), not just advertised from a
     stale discovery cache.

Usage:
    python3 devops/scripts/check_inter_pi_communication.py --role pi1
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML is required (pip install pyyaml / apt install python3-yaml)", file=sys.stderr)
    sys.exit(2)

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_NETWORK_CONFIG = _ROOT / "config" / "distributed" / "robot_network.yaml"
_PING_TIMEOUT_SEC = 2
_TOPIC_ECHO_TIMEOUT_SEC = 5


def _load_network_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _check_domain_id(expected: int) -> tuple[bool, str]:
    actual = os.environ.get("ROS_DOMAIN_ID")
    if actual is None:
        return False, "ROS_DOMAIN_ID is not set in this shell at all"
    if str(actual) != str(expected):
        return False, f"ROS_DOMAIN_ID={actual}, expected {expected} (robot_network.yaml)"
    return True, f"ROS_DOMAIN_ID={actual} matches robot_network.yaml"


def _check_ping(ip: str) -> tuple[bool, str]:
    # -c1/-W2 on Linux; -n1 on Windows dev-box testing of this script.
    if sys.platform.startswith("win"):
        cmd = ["ping", "-n", "1", "-w", str(_PING_TIMEOUT_SEC * 1000), ip]
    else:
        cmd = ["ping", "-c", "1", "-W", str(_PING_TIMEOUT_SEC), ip]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=_PING_TIMEOUT_SEC + 2)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return False, f"ping failed to run: {exc}"
    if result.returncode == 0:
        return True, f"{ip} reachable at L3"
    return False, f"{ip} NOT reachable at L3 -- check cabling/switch/static IP config"


def _ros2_topic_list() -> list[str] | None:
    if not shutil.which("ros2"):
        return None
    try:
        result = subprocess.run(
            ["ros2", "topic", "list"], capture_output=True, timeout=10, text=True
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _check_topic_advertised(topic: str, all_topics: list[str] | None) -> tuple[bool, str]:
    if all_topics is None:
        return False, "ros2 not on PATH or 'ros2 topic list' failed -- source the workspace first"
    if topic in all_topics:
        return True, f"{topic} advertised"
    return False, f"{topic} NOT advertised -- DDS discovery has not found this peer"


def _check_topic_live(topic: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["ros2", "topic", "echo", "--once", topic],
            capture_output=True,
            timeout=_TOPIC_ECHO_TIMEOUT_SEC,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return False, (
            f"{topic} advertised but no message received within "
            f"{_TOPIC_ECHO_TIMEOUT_SEC}s -- publisher may be stalled or "
            "discovery is one-way (asymmetric firewall/routing)"
        )
    if result.returncode == 0 and result.stdout.strip():
        return True, f"{topic} receiving live data"
    return False, f"{topic}: echo failed ({result.stderr.strip() or 'no output'})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--role", required=True, choices=["pi1", "pi2", "pi3"])
    parser.add_argument("--network-config", type=Path, default=_DEFAULT_NETWORK_CONFIG)
    parser.add_argument(
        "--skip-live-data",
        action="store_true",
        help="Skip the bounded ros2 topic echo check (faster, less thorough)",
    )
    args = parser.parse_args(argv)

    cfg = _load_network_config(args.network_config)
    pis = cfg["pis"]
    ros2_cfg = cfg["ros2"]
    peers = {role: info for role, info in pis.items() if role != args.role}

    print(f"== Inter-Pi communication check from {args.role} ==\n")
    overall_ok = True

    ok, msg = _check_domain_id(ros2_cfg["ros_domain_id"])
    print(f"[{'PASS' if ok else 'FAIL'}] {msg}")
    overall_ok &= ok

    all_topics = _ros2_topic_list()

    for peer_role, peer_info in peers.items():
        print(f"\n-- Checking {peer_role} ({peer_info['hostname']}, {peer_info['static_ip']}) --")

        ok, msg = _check_ping(peer_info["static_ip"])
        print(f"[{'PASS' if ok else 'FAIL'}] {msg}")
        if not ok:
            overall_ok = False
            print("       (skipping DDS-level checks -- no point without L3 reachability)")
            continue

        heartbeat_topic = peer_info["heartbeat_topic"]
        ok, msg = _check_topic_advertised(heartbeat_topic, all_topics)
        print(f"[{'PASS' if ok else 'FAIL'}] {msg}")
        overall_ok &= ok
        if not ok:
            continue

        if not args.skip_live_data:
            ok, msg = _check_topic_live(heartbeat_topic)
            print(f"[{'PASS' if ok else 'FAIL'}] {msg}")
            overall_ok &= ok

    print("\n================================")
    if overall_ok:
        print("RESULT: all peers reachable, discovered, and live.")
        return 0
    print("RESULT: INTER-PI COMMUNICATION PROBLEM DETECTED -- see FAIL lines above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
