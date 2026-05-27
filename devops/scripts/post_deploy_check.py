#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

REQUIRED_TOPICS = [
    "/scan",
    "/imu/data",
    "/camera/color/image_raw",
    "/bonbon/battery/state",
    "/bonbon/estop/state",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run BonBon post-deployment verification.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    checks = {
        "all services started": _systemd_ok(args.dry_run),
        "ROS2 graph healthy": _ros2_graph_ok(args.dry_run),
        "Safety Supervisor healthy": _truthy("BONBON_SAFETY_SUPERVISOR_RUNNING", args.dry_run),
        "sensor topics publishing": _topics_ok(args.dry_run),
        "dashboard reachable": _http_ok(
            f"http://127.0.0.1:{os.getenv('BONBON_DASHBOARD_PORT', '8080')}/health", args.dry_run
        ),
        "logs active": _path_ok(os.getenv("BONBON_LOG_DIR", "/var/log/bonbon"), args.dry_run),
        "metrics active": _http_ok(
            f"http://127.0.0.1:{os.getenv('BONBON_PROMETHEUS_PORT', '9090')}/-/healthy",
            args.dry_run,
        ),
        "no critical errors": _truthy("BONBON_NO_CRITICAL_ERRORS", args.dry_run),
        "rollback not required": _truthy("BONBON_ROLLBACK_NOT_REQUIRED", args.dry_run),
    }
    failed = [name for name, passed in checks.items() if not passed]
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    if failed:
        print("Post-deployment checks failed: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


def _truthy(name: str, dry_run: bool) -> bool:
    if dry_run:
        return True
    return os.getenv(name, "").lower() in {"1", "true", "yes", "ok"}


def _systemd_ok(dry_run: bool) -> bool:
    if dry_run:
        return True
    if not shutil.which("systemctl"):
        return False
    services = [
        "bonbon-core.service",
        "bonbon-navigation.service",
        "bonbon-perception.service",
        "bonbon-speech.service",
        "bonbon-tts.service",
        "bonbon-safety.service",
        "bonbon-dashboard.service",
        "bonbon-monitoring.service",
    ]
    return all(
        subprocess.run(["systemctl", "is-active", "--quiet", service]).returncode == 0
        for service in services
    )


def _ros2_graph_ok(dry_run: bool) -> bool:
    if dry_run:
        return True
    if not shutil.which("ros2"):
        return False
    result = subprocess.run(["ros2", "node", "list"], text=True, capture_output=True, timeout=10)
    return result.returncode == 0 and "safety" in result.stdout.lower()


def _topics_ok(dry_run: bool) -> bool:
    if dry_run:
        return True
    if not shutil.which("ros2"):
        return False
    result = subprocess.run(["ros2", "topic", "list"], text=True, capture_output=True, timeout=10)
    return result.returncode == 0 and all(topic in result.stdout for topic in REQUIRED_TOPICS)


def _http_ok(url: str, dry_run: bool) -> bool:
    if dry_run:
        return True
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return 200 <= response.status < 500
    except (urllib.error.URLError, TimeoutError):
        return False


def _path_ok(path: str, dry_run: bool) -> bool:
    return True if dry_run else os.path.isdir(path)


if __name__ == "__main__":
    raise SystemExit(main())
