#!/usr/bin/env python3
"""Validate the BonBon systemd boot topology and refuse a duplicate-Safety-
Supervisor deployment.

Queries `systemctl is-enabled` for every known BonBon unit, optionally
`ros2 node list` for the live safety-supervisor count, classifies the mode
via devops/scripts/boot_topology.py, prints a report, writes the result to
devops/project-status/boot_topology.json (so the dashboard can surface it),
and exits non-zero on an invalid topology.

Run on the host (where systemctl lives), not inside a container:
    python3 scripts/validate_boot_topology.py
    python3 scripts/validate_boot_topology.py --check-running-nodes

Exit code 0 = valid topology; 1 = invalid (duplicate / missing safety).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "devops" / "scripts"))

from boot_topology import (  # noqa: E402
    MODULAR_PI_UNITS,
    MONOLITHIC_UNIT,
    classify_topology,
)

_ALL_UNITS = sorted({MONOLITHIC_UNIT} | set(MODULAR_PI_UNITS))
_OUTPUT = _ROOT / "devops" / "project-status" / "boot_topology.json"


def _enabled_units() -> set[str]:
    """Return the set of BonBon units systemctl reports as `enabled`."""
    if not shutil.which("systemctl"):
        print(
            "  [WARN] systemctl not found — cannot read enabled units "
            "(are you on the Pi/host, not a container?)",
            file=sys.stderr,
        )
        return set()
    enabled = set()
    for unit in _ALL_UNITS:
        try:
            out = subprocess.run(
                ["systemctl", "is-enabled", f"{unit}.service"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            # is-enabled prints "enabled"/"disabled"/"static"/... on stdout.
            if out.stdout.strip() == "enabled":
                enabled.add(unit)
        except (subprocess.SubprocessError, OSError):
            continue
    return enabled


def _running_safety_count() -> int | None:
    """Count live safety_supervisor_node processes via `ros2 node list`."""
    if not shutil.which("ros2"):
        return None
    try:
        out = subprocess.run(["ros2", "node", "list"], capture_output=True, text=True, timeout=10)
    except (subprocess.SubprocessError, OSError):
        return None
    return sum(1 for line in out.stdout.splitlines() if "safety_supervisor_node" in line)


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate BonBon boot topology.")
    ap.add_argument(
        "--check-running-nodes",
        action="store_true",
        help="also count live safety_supervisor_node via `ros2 node list`",
    )
    ap.add_argument(
        "--enabled",
        nargs="*",
        default=None,
        help="override: treat these unit names as enabled (for testing)",
    )
    args = ap.parse_args()

    enabled = set(args.enabled) if args.enabled is not None else _enabled_units()
    observed = _running_safety_count() if args.check_running_nodes else None

    result = classify_topology(enabled, observed_safety_supervisors=observed)

    print("======== BonBon boot-topology validation ========")
    print(f"  mode:            {result.mode.value}")
    print(f"  valid:           {result.valid}")
    print(f"  enabled units:   {', '.join(result.enabled_units) or '(none)'}")
    if observed is not None:
        print(f"  running safety supervisors: {observed}")
    for r in result.reasons:
        print(f"  - {r}")
    if not result.valid and result.remediation:
        print("\n  REMEDIATION:")
        for line in result.remediation.splitlines():
            print(f"    {line}")
    print("==================================================")

    try:
        _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        _OUTPUT.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        print(f"  wrote {_OUTPUT.relative_to(_ROOT)}")
    except OSError as exc:
        print(f"  [WARN] could not write {_OUTPUT}: {exc}", file=sys.stderr)

    return 0 if result.valid else 1


if __name__ == "__main__":
    sys.exit(main())
