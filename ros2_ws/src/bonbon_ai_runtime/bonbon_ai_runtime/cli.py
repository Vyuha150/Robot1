"""ai_runtime_bench — select a runtime per config and benchmark it on the
target device. Run on the Pi (with the AI HAT) to confirm Hailo is actually
being used and to measure FPS:

    ros2 run bonbon_ai_runtime ai_runtime_bench --mode auto --runs 50

Honest by construction: it reports the *actually selected* runtime and
whether a fallback is active — it cannot fake a Hailo PASS without a Hailo.
"""

from __future__ import annotations

import argparse
import json
import sys

from bonbon_ai_runtime.interface import RuntimeKind
from bonbon_ai_runtime.runtime_selector import RuntimeMode, RuntimeSelector, RuntimeSpec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Select + benchmark a vision runtime.")
    ap.add_argument("--mode", default="auto", choices=[m.value for m in RuntimeMode])
    ap.add_argument("--hailo-hef", default="", help="path to .hef (Hailo)")
    ap.add_argument("--cpu-onnx", default="", help="path to .onnx (CPU)")
    ap.add_argument("--runs", type=int, default=30)
    args = ap.parse_args(argv)

    spec = RuntimeSpec(
        mode=RuntimeMode(args.mode),
        model_paths={
            RuntimeKind.HAILO: args.hailo_hef,
            RuntimeKind.CPU: args.cpu_onnx,
        },
    )
    result = RuntimeSelector().select(spec)
    runtime = result.runtime
    runtime.warmup(runs=3)
    bench = runtime.benchmark(runs=args.runs)

    report = {
        "selection": result.to_dict(),
        "benchmark": {
            "runtime": bench.runtime,
            "runs": bench.runs,
            "mean_ms": round(bench.mean_ms, 2),
            "p50_ms": round(bench.p50_ms, 2),
            "p95_ms": round(bench.p95_ms, 2),
            "fps": round(bench.fps, 1),
            "failures": bench.failures,
        },
        "health": runtime.health().__dict__,
    }
    print(json.dumps(report, indent=2, default=str))
    runtime.shutdown()
    # Non-zero if we silently fell back to mock (i.e. no real accelerator).
    return 0 if result.selected_kind != RuntimeKind.MOCK or args.mode == "mock" else 2


if __name__ == "__main__":
    sys.exit(main())
