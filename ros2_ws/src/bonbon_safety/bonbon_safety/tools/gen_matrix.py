"""Generate ``docs/FAILURE_MODES.md`` from the failure catalogue.

The catalogue (`bonbon_safety/core/failure_catalog.py`) is the single source of
truth; this script renders it to Markdown so the published matrix can never
drift from the runtime registry.

Usage::

    python -m bonbon_safety.tools.gen_matrix            # writes docs/FAILURE_MODES.md
    python -m bonbon_safety.tools.gen_matrix --stdout   # print to stdout
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from bonbon_safety.core.failure_catalog import CATEGORY_RANGES, numbered_catalog

_LEVEL = {
    0: "L0 normal", 1: "L1 degraded", 2: "L2 safe-pause",
    3: "L3 safe-stop", 4: "L4 e-stop", 5: "L5 human",
}


def render() -> str:
    """Render the full failure-mode matrix as a Markdown string."""
    rows = numbered_catalog()
    by_num = {n: d for n, d in rows}

    out: list[str] = []
    out.append("# BonBon Failure-Mode Matrix\n\n")
    out.append(
        "> Generated from `bonbon_safety/core/failure_catalog.py` — the single "
        "source of truth. Regenerate with `python -m bonbon_safety.tools.gen_matrix`. "
        "Integrity is enforced by `tests/test_failure_catalog.py`.\n\n"
    )
    out.append("## Fallback levels\n\n")
    out.append(
        "| Level | Meaning | Operator alert | Self-recoverable |\n"
        "|---|---|---|---|\n"
        "| L0 | normal operation | no | — |\n"
        "| L1 | degraded mode | no | yes |\n"
        "| L2 | safe pause | no | yes |\n"
        "| L3 | safe stop | yes | yes |\n"
        "| L4 | emergency stop | yes | no (manual reset) |\n"
        "| L5 | human intervention required | yes | no |\n"
    )

    for cat, (lo, hi) in CATEGORY_RANGES.items():
        out.append(f"\n## {cat}\n\n")
        out.append(
            "| # | Failure | Module | Detection | Level | Recovery | "
            "User-facing | Operator alert | Test coverage |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
        )
        for n in range(lo, hi + 1):
            d = by_num[n]
            alert = "yes" if (d.operator_alert or int(d.level) >= 3) else "no"
            out.append(
                f"| {n} | {d.fault_id} | {d.module} | {d.detection} | "
                f"{_LEVEL[int(d.level)]} | {d.recovery} | {d.user_facing} | "
                f"{alert} | catalog + handler integrity tests |\n"
            )
    return "".join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate the failure-mode matrix.")
    parser.add_argument("--stdout", action="store_true", help="print instead of writing")
    args = parser.parse_args(argv)

    content = render()
    if args.stdout:
        print(content)
        return 0

    # docs/ lives at the package root (two levels up from this file's dir).
    pkg_root = Path(__file__).resolve().parents[2]
    out_path = pkg_root / "docs" / "FAILURE_MODES.md"
    os.makedirs(out_path.parent, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
