#!/usr/bin/env python3
"""Install, start, and verify one Pi's systemd units for the 3-Pi split
deployment (3-Pi Phase 8).

Confirmed via audit: deployment/systemd/pi{1,2,3}/*.service already exist,
each with a real, correct `Requires=`/`After=` dependency graph (verified
by reading every unit file on all three Pis) -- but no reusable script
existed anywhere to install/enable/start them in that order, or to verify
the result. The only prior guidance was hand-written, Pi-2-specific manual
commands (docs/PI2_CONTAINER_BUILD_AND_SYSTEMD_DEPLOYMENT_COMMANDS.md).
This script generalises that to all three Pis and computes the start
order FROM each unit's own `Requires=` graph (topological sort) instead of
a fourth hand-maintained copy of the same ordering.

Same dry-run-by-default / --apply-requires-root convention as
bootstrap_pi_network.py -- this touches system-level systemd state on real
hardware, so an accidental run must never silently reconfigure a machine.

Usage:
    # Pi-2, see the install + start plan (no changes):
    python3 devops/scripts/pi_systemd_manager.py --role pi2 --plan

    # Pi-2, actually install + enable the units (root required):
    sudo python3 devops/scripts/pi_systemd_manager.py --role pi2 --apply

    # Pi-2, install + enable + start in dependency order (root required):
    sudo python3 devops/scripts/pi_systemd_manager.py --role pi2 --apply --start

    # Any Pi, any time: check enabled/active status, no changes:
    python3 devops/scripts/pi_systemd_manager.py --role pi2 --verify
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMD_DEST = Path("/etc/systemd/system")

# Unit dependency targets that are never one of THIS role's own units --
# excluded from the topological sort since they're satisfied by systemd/
# the OS itself, not by another unit this script installs.
_EXTERNAL_TARGETS = {"docker.service", "network-online.target", "graphical.target"}


class SystemdManagerError(RuntimeError):
    pass


def _unit_dir(role: str) -> Path:
    return _ROOT / "deployment" / "systemd" / role


def _parse_unit_file(path: Path) -> dict:
    """Extracts the fields this script needs from a systemd unit file.
    Deliberately a plain line scanner, not configparser -- `After=`/
    `Requires=` are space-separated multi-value keys configparser doesn't
    split automatically, and unit files aren't guaranteed strict INI
    (duplicate keys across sections are legal in systemd, not in
    configparser)."""
    requires: list[str] = []
    after: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("Requires="):
            requires.extend(line[len("Requires=") :].split())
        elif line.startswith("After="):
            after.extend(line[len("After=") :].split())
    return {"name": path.name, "requires": requires, "after": after}


def load_units(role: str) -> list[dict]:
    unit_dir = _unit_dir(role)
    if not unit_dir.is_dir():
        raise SystemdManagerError(f"no systemd unit directory for role '{role}': {unit_dir}")
    paths = sorted(unit_dir.glob("*.service"))
    if not paths:
        raise SystemdManagerError(f"no *.service files found in {unit_dir}")
    return [_parse_unit_file(p) for p in paths]


def topological_order(units: list[dict]) -> list[str]:
    """Kahn's algorithm over each unit's `Requires=` + `After=` edges
    (same-role units only). `After=` alone is a systemd ordering hint, not
    a hard dependency (systemd itself won't block on it without a matching
    `Requires=`) -- but for the purpose of "what sequence should THIS
    script issue `systemctl start` in," respecting it too gives a safer,
    more complete order (e.g. bonbon-pi3-actuation.service `Requires=`
    only bonbon-pi3-safety.service but `After=`s bonbon-pi3-hal.service
    too -- confirmed by reading the real unit file). This never edits or
    reinterprets the unit files' own systemd semantics, only this script's
    own start ordering. Raises SystemdManagerError on a cycle -- a real
    configuration bug, never silently resolved."""
    names = {u["name"] for u in units}
    requires_of = {
        u["name"]: sorted(
            {
                r
                for r in (*u["requires"], *u.get("after", ()))
                if r in names and r not in _EXTERNAL_TARGETS
            }
        )
        for u in units
    }
    remaining = dict(requires_of)
    ordered: list[str] = []
    while remaining:
        ready = sorted(name for name, deps in remaining.items() if not deps)
        if not ready:
            raise SystemdManagerError(
                f"circular Requires= dependency among: {sorted(remaining)}"
            )
        for name in ready:
            ordered.append(name)
            del remaining[name]
        for deps in remaining.values():
            for name in ready:
                if name in deps:
                    deps.remove(name)
    return ordered


def _run(cmd: list[str], apply: bool, timeout: float = 120.0) -> subprocess.CompletedProcess | None:
    printable = " ".join(cmd)
    if not apply:
        print(f"[DRY RUN] {printable}")
        return None
    print(f"[APPLY]   {printable}")
    return subprocess.run(cmd, timeout=timeout)


def cmd_plan_or_apply(args: argparse.Namespace) -> int:
    try:
        units = load_units(args.role)
        order = topological_order(units)
    except SystemdManagerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"== {args.role}: {len(order)} unit(s), install/start order ==")
    for i, name in enumerate(order, 1):
        print(f"  {i}. {name}")

    if args.apply and os.name == "posix" and os.geteuid() != 0:
        print("--apply requires root (systemctl enable/start need it)", file=sys.stderr)
        return 2

    unit_dir = _unit_dir(args.role)
    _run(["cp", *[str(unit_dir / n) for n in order], str(_SYSTEMD_DEST)], args.apply)
    _run(["systemctl", "daemon-reload"], args.apply)
    for name in order:
        _run(["systemctl", "enable", name], args.apply)

    if args.start:
        failures: list[str] = []
        for name in order:
            result = _run(["systemctl", "start", name], args.apply)
            if args.apply and result is not None and result.returncode != 0:
                failures.append(name)
                print(f"       FAILED to start {name} -- dependents may also fail", file=sys.stderr)
        if failures:
            print(f"\n{len(failures)} unit(s) failed to start: {failures}", file=sys.stderr)
            return 1

    print(f"\n== {args.role} systemd {'applied' if args.apply else 'plan printed'} ==")
    return 0


def _systemctl(*args: str) -> str:
    """Returns stripped stdout, or an honest placeholder if systemctl isn't
    available at all (e.g. this dev sandbox) -- never raises, so --verify
    can run anywhere and simply report FAIL rather than crash."""
    try:
        result = subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return "systemctl-unavailable"
    return (result.stdout.strip() or result.stderr.strip() or "unknown").strip()


def cmd_verify(args: argparse.Namespace) -> int:
    try:
        units = load_units(args.role)
    except SystemdManagerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"== {args.role}: verifying {len(units)} unit(s) ==")
    all_ok = True
    for u in sorted(units, key=lambda u: u["name"]):
        name = u["name"]
        enabled = _systemctl("is-enabled", name)
        active = _systemctl("is-active", name)
        enabled_ok = enabled == "enabled"
        active_ok = active in ("active", "activating")
        ok = enabled_ok and active_ok
        all_ok &= ok
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: enabled={enabled}, active={active}")

    print("\n================================")
    print("RESULT: all units enabled and active." if all_ok else "RESULT: SOME UNITS NOT READY -- see FAIL lines above.")
    return 0 if all_ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--role", required=True, choices=["pi1", "pi2", "pi3"])
    parser.add_argument("--apply", action="store_true", help="Actually install/enable. Default: dry run.")
    parser.add_argument("--start", action="store_true", help="Also start units, in dependency order.")
    parser.add_argument("--verify", action="store_true", help="Only check enabled/active status; no changes.")
    args = parser.parse_args(argv)

    if args.verify:
        return cmd_verify(args)
    return cmd_plan_or_apply(args)


if __name__ == "__main__":
    raise SystemExit(main())
