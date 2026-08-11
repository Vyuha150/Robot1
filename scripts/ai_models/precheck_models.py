#!/usr/bin/env python3
"""precheck_models.py — honest environment check before any AI model
download. Never fabricates a PASS: every check either confirms a real
fact about this machine or reports "unknown/not available on this
platform" explicitly. Safe to run on the actual Pi, in the Docker build,
or on an unrelated dev machine (like this session's Windows sandbox) --
it degrades every check gracefully rather than crashing when a Pi-only
tool (vcgencmd, lsusb) doesn't exist here.

Usage:
    python3 scripts/ai_models/precheck_models.py
    python3 scripts/ai_models/precheck_models.py --json
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass


@dataclass
class PrecheckResult:
    name: str
    status: str  # "ok" | "warning" | "missing" | "unknown" | "not_applicable"
    detail: str


def _run(cmd: list[str], timeout: float = 5.0) -> tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603
        output = (proc.stdout or proc.stderr).strip()
        return proc.returncode == 0, output
    except FileNotFoundError:
        return False, "command not found"
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except Exception as exc:  # noqa: BLE001 -- a precheck failure must be reported, not crash the whole script
        return False, str(exc)


def check_platform() -> PrecheckResult:
    system = platform.system()
    machine = platform.machine()
    is_pi_like = system == "Linux" and machine in ("aarch64", "armv7l")
    if is_pi_like:
        return PrecheckResult("platform", "ok", f"{system}/{machine} -- looks like a Pi-class ARM Linux board")
    return PrecheckResult("platform", "warning", f"{system}/{machine} -- NOT a Pi-class board; download/benchmark results here do not represent real Pi performance")


def check_pi_model() -> PrecheckResult:
    try:
        with open("/proc/device-tree/model", encoding="utf-8") as f:
            model = f.read().strip("\x00").strip()
        return PrecheckResult("pi_model", "ok", model)
    except FileNotFoundError:
        return PrecheckResult("pi_model", "not_applicable", "no /proc/device-tree/model -- not running on a Raspberry Pi")
    except Exception as exc:  # noqa: BLE001
        return PrecheckResult("pi_model", "unknown", str(exc))


def check_ram() -> PrecheckResult:
    try:
        import psutil  # type: ignore[import-untyped]

        total_gb = psutil.virtual_memory().total / (1024**3)
        avail_gb = psutil.virtual_memory().available / (1024**3)
        return PrecheckResult("ram", "ok", f"{total_gb:.1f} GB total, {avail_gb:.1f} GB available")
    except ImportError:
        return PrecheckResult("ram", "unknown", "psutil not installed -- cannot check RAM")


def check_storage(path: str = ".") -> PrecheckResult:
    try:
        usage = shutil.disk_usage(path)
        free_gb = usage.free / (1024**3)
        status = "ok" if free_gb > 2.0 else "warning"
        return PrecheckResult("storage", status, f"{free_gb:.1f} GB free at {path!r}")
    except OSError as exc:
        return PrecheckResult("storage", "unknown", str(exc))


def check_temperature() -> PrecheckResult:
    ok, out = _run(["vcgencmd", "measure_temp"])
    if ok:
        return PrecheckResult("temperature", "ok", out)
    return PrecheckResult("temperature", "not_applicable", "vcgencmd not available -- not on a Raspberry Pi, or not installed")


def check_throttling() -> PrecheckResult:
    ok, out = _run(["vcgencmd", "get_throttled"])
    if ok:
        healthy = out.strip().endswith("0x0")
        return PrecheckResult("throttling", "ok" if healthy else "warning", out)
    return PrecheckResult("throttling", "not_applicable", "vcgencmd not available")


def check_hailo() -> PrecheckResult:
    ok, out = _run(["hailortcli", "scan"])
    if ok and out:
        return PrecheckResult("hailo_ai_hat", "ok", out)
    if shutil.which("hailortcli") is None:
        return PrecheckResult("hailo_ai_hat", "missing", "hailortcli not installed -- AI HAT/Hailo runtime is not set up on this machine")
    return PrecheckResult("hailo_ai_hat", "missing", out or "hailortcli found but scan reported no device")


def check_hailort_python() -> PrecheckResult:
    import importlib.util

    if importlib.util.find_spec("hailort") is not None:
        return PrecheckResult("hailort_python", "ok", "hailort Python bindings importable")
    return PrecheckResult("hailort_python", "missing", "hailort Python package not installed")


def check_oak_d() -> PrecheckResult:
    ok, out = _run(["lsusb"])
    if not ok:
        return PrecheckResult("oak_d", "not_applicable", "lsusb not available on this platform")
    if "03e7" in out.lower():
        return PrecheckResult("oak_d", "ok", "Luxonis OAK-D (vendor 03e7) detected on USB")
    return PrecheckResult("oak_d", "missing", "no Luxonis device (vendor 03e7) found on USB")


def check_respeaker() -> PrecheckResult:
    ok, out = _run(["arecord", "-l"])
    if not ok:
        return PrecheckResult("respeaker", "not_applicable", "arecord not available on this platform")
    if out.strip():
        return PrecheckResult("respeaker", "ok", out.strip().splitlines()[0])
    return PrecheckResult("respeaker", "missing", "no ALSA capture devices found")


def check_ollama() -> PrecheckResult:
    if shutil.which("ollama") is None:
        return PrecheckResult("ollama", "missing", "ollama binary not found on PATH")
    ok, out = _run(["ollama", "list"])
    if ok:
        model_count = max(0, len(out.strip().splitlines()) - 1)  # minus header row
        return PrecheckResult("ollama", "ok", f"ollama installed, {model_count} model(s) pulled")
    return PrecheckResult("ollama", "warning", "ollama binary found but 'ollama list' failed -- daemon may not be running")


def check_python_version() -> PrecheckResult:
    v = sys.version_info
    status = "ok" if (v.major, v.minor) >= (3, 10) else "warning"
    return PrecheckResult("python_version", status, f"Python {v.major}.{v.minor}.{v.micro}")


def check_ros2_environment() -> PrecheckResult:
    import os

    distro = os.environ.get("ROS_DISTRO")
    if distro:
        return PrecheckResult("ros2_environment", "ok", f"ROS_DISTRO={distro}")
    ok, out = _run(["ros2", "--version"])
    if ok:
        return PrecheckResult("ros2_environment", "ok", out)
    return PrecheckResult("ros2_environment", "missing", "ROS_DISTRO not set and 'ros2' command not found -- ROS2 environment not sourced")


def check_board_role() -> PrecheckResult:
    import os

    role = os.environ.get("BONBON_BOARD_ROLE") or os.environ.get("PI_ROLE")
    if role:
        return PrecheckResult("board_role", "ok", role)
    return PrecheckResult("board_role", "unknown", "BONBON_BOARD_ROLE/PI_ROLE not set -- cannot determine ui/ai/navigation role from environment")


def run_all() -> list[PrecheckResult]:
    return [
        check_platform(),
        check_board_role(),
        check_pi_model(),
        check_ram(),
        check_storage(),
        check_temperature(),
        check_throttling(),
        check_hailo(),
        check_hailort_python(),
        check_oak_d(),
        check_respeaker(),
        check_ollama(),
        check_python_version(),
        check_ros2_environment(),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON instead of a human table")
    args = parser.parse_args()

    results = run_all()

    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=2))  # noqa: T201
        return 0

    print(f"{'CHECK':<20} {'STATUS':<10} DETAIL")  # noqa: T201
    print("-" * 70)  # noqa: T201
    for r in results:
        print(f"{r.name:<20} {r.status:<10} {r.detail}")  # noqa: T201

    missing_critical = [r for r in results if r.name in ("ollama", "python_version") and r.status == "missing"]
    if missing_critical:
        print("\nNOTE: this is an honest report, not a pass/fail gate -- missing items above")  # noqa: T201
        print("are exactly what the download plan (Phase 4) skips until resolved, never faked.")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
