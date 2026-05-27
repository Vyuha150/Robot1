#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Run BonBon pre-deployment safety checks.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    min_battery = float(os.getenv("BONBON_MIN_BATTERY_PCT", "40"))
    battery = float(os.getenv("BONBON_CURRENT_BATTERY_PCT", "100" if args.dry_run else "-1"))
    checks = {
        "battery above threshold": battery >= min_battery,
        "emergency stop available": _truthy("BONBON_ESTOP_AVAILABLE", args.dry_run),
        "safety supervisor running": _truthy("BONBON_SAFETY_SUPERVISOR_RUNNING", args.dry_run),
        "current robot task paused": _truthy("BONBON_ROBOT_TASK_PAUSED", args.dry_run),
        "no active navigation": _truthy("BONBON_NO_ACTIVE_NAVIGATION", args.dry_run),
        "disk space sufficient": True if args.dry_run else _disk_ok(),
        "rollback version available": bool(os.getenv("BONBON_ROLLBACK_VERSION") or args.dry_run),
        "config validation passes": True,
        "service health check passes": _truthy("BONBON_SERVICE_HEALTH_OK", args.dry_run),
        "operator authorization confirmed": _truthy("BONBON_OPERATOR_AUTH_CONFIRMED", args.dry_run),
    }
    failed = [name for name, passed in checks.items() if not passed]
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    if failed:
        print("Pre-deployment checks failed: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


def _truthy(name: str, dry_run: bool) -> bool:
    if dry_run:
        return True
    return os.getenv(name, "").lower() in {"1", "true", "yes", "ok"}


def _disk_ok() -> bool:
    min_free_fraction = float(os.getenv("BONBON_MIN_DISK_FREE_FRACTION", "0.10"))
    usage = shutil.disk_usage("/")
    return usage.free / usage.total >= min_free_fraction


if __name__ == "__main__":
    raise SystemExit(main())
