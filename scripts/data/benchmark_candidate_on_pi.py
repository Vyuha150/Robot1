#!/usr/bin/env python3
"""scripts/data/benchmark_candidate_on_pi.py

Gathers the real, on-device RAM/CPU/temperature numbers a deployment gate
needs (criteria 4 and 5), then writes a CandidateBenchmark-shaped JSON file
that scripts/data/evaluate_candidate_model.py can consume.

Runs `edge-side` -- meant to be invoked ON the target Pi. Off-Pi, the
hardware-specific readings (temperature always, RAM/CPU still readable via
psutil if installed) are reported as null rather than guessed, so the
resulting candidate JSON's `temperature_c` is null and
model_evaluation.evaluate_for_deployment correctly reports that criterion
UNVERIFIED rather than silently PASSED. Latency and accuracy/target-metric
values are NOT measured here -- those come from a capability-specific
benchmark harness (e.g. bonbon_ai_model_registry.model_benchmark_runner)
and are merged in via --latency-ms/--target-metric-value, since this
script has no generic way to invoke an arbitrary model itself.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bonbon_data_pipeline.dataset_downloader import is_edge_device  # noqa: E402

try:
    import psutil

    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

_THERMAL_ZONE_PATH = Path("/sys/class/thermal/thermal_zone0/temp")


def read_temperature_c() -> float | None:
    """Real Pi CPU temperature via the standard Linux thermal_zone sysfs
    path. Returns None (never a guess) when unreadable -- e.g. this dev
    machine, or a Pi without a matching thermal_zone index."""
    try:
        raw = _THERMAL_ZONE_PATH.read_text(encoding="utf-8").strip()
        return float(raw) / 1000.0
    except (OSError, ValueError):
        return None


def read_ram_mb() -> float | None:
    if not _HAS_PSUTIL:
        return None
    return psutil.virtual_memory().used / (1024 * 1024)


def read_cpu_percent() -> float | None:
    if not _HAS_PSUTIL:
        return None
    return psutil.cpu_percent(interval=1.0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--capability", required=True)
    parser.add_argument("--target-metric-name", required=True)
    parser.add_argument("--target-metric-value", type=float, required=True)
    parser.add_argument("--target-metric-threshold", type=float, required=True)
    parser.add_argument("--latency-ms", type=float, default=None)
    parser.add_argument("--latency-target-ms", type=float, default=None)
    parser.add_argument("--ram-baseline-mb", type=float, default=None)
    parser.add_argument("--thermal-limit-c", type=float, default=None)
    parser.add_argument("--fallback-verified", action="store_true")
    parser.add_argument("--regression-pass-rate", type=float, default=0.0)
    parser.add_argument("--total-regression-scenarios", type=int, default=0)
    parser.add_argument("--out", type=Path, default=Path("candidate_benchmark.json"))
    args = parser.parse_args()

    on_edge = is_edge_device()
    temperature_c = read_temperature_c() if on_edge else None
    ram_mb = read_ram_mb()
    cpu_percent = read_cpu_percent()

    if not on_edge:
        print(
            "NOTE: not running on a detected Pi/ARM device -- temperature_c will be null "
            "(honestly UNVERIFIED, not guessed). Run this script on the real target Pi "
            "before a production promotion decision.",
            file=sys.stderr,
        )

    candidate = {
        "model_id": args.model_id,
        "model_version": args.model_version,
        "dataset_version": args.dataset_version,
        "capability": args.capability,
        "target_metric_name": args.target_metric_name,
        "target_metric_value": args.target_metric_value,
        "target_metric_threshold": args.target_metric_threshold,
        "latency_ms": args.latency_ms,
        "latency_target_ms": args.latency_target_ms,
        "ram_mb": ram_mb,
        "ram_baseline_mb": args.ram_baseline_mb,
        "temperature_c": temperature_c,
        "thermal_limit_c": args.thermal_limit_c,
        "fallback_verified": args.fallback_verified,
        "regression_pass_rate": args.regression_pass_rate,
        "total_regression_scenarios": args.total_regression_scenarios,
        "cpu_percent": cpu_percent,
    }

    args.out.write_text(json.dumps(candidate, indent=2), encoding="utf-8")
    print(f"Wrote {args.out}")
    print(f"on_edge_device={on_edge}  temperature_c={temperature_c}  ram_mb={ram_mb}  cpu_percent={cpu_percent}")
    print(f"\nNext: python scripts/data/evaluate_candidate_model.py {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
