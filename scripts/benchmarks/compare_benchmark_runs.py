#!/usr/bin/env python3
"""scripts/benchmarks/compare_benchmark_runs.py -- Phase 13.

Compares two persisted bonbon_benchmarks runs (JSON files written by
bonbon_benchmarks.benchmark_reporter.persist()) and reports:

    Metric | Before | After | Improvement % | Pass/Fail | Notes

Matches metrics by (category, metric_name, board, scenario) -- an exact
key, not a fuzzy name match, so a comparison never silently pairs up two
unrelated measurements. A metric present in only one run, or BLOCKED on
either side, is reported honestly (no improvement % computed for it,
never a fabricated percentage) rather than silently dropped.

Usage:
    python3 scripts/benchmarks/compare_benchmark_runs.py --before reports/baseline.json --after reports/optimized.json
    python3 scripts/benchmarks/compare_benchmark_runs.py --before reports/baseline.json --after reports/optimized.json --out docs/benchmarks/EFFICIENCY_IMPROVEMENT_COMPARISON.md
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ComparisonRow:
    category: str
    metric_name: str
    board: str
    scenario: str
    before_status: str
    after_status: str
    before_p95: float | None
    after_p95: float | None
    unit: str
    higher_is_better: bool
    improvement_pct: float | None
    verdict: str
    notes: str


def _key(category: str, m: dict) -> tuple:
    return (category, m["metricName"], m["board"], m["scenario"])


def _flatten(run: dict) -> dict[tuple, dict]:
    flat: dict[tuple, dict] = {}
    for cat in run.get("categories", []):
        for m in cat.get("metrics", []):
            flat[_key(cat["category"], m)] = m
    return flat


def compare(before: dict, after: dict) -> list[ComparisonRow]:
    before_flat = _flatten(before)
    after_flat = _flatten(after)
    all_keys = sorted(set(before_flat) | set(after_flat))

    rows: list[ComparisonRow] = []
    for key in all_keys:
        category, metric_name, board, scenario = key
        b = before_flat.get(key)
        a = after_flat.get(key)

        if b is None:
            rows.append(ComparisonRow(
                category, metric_name, board, scenario, "MISSING", a["status"], None,
                a["p95"], a["unit"], a["higherIsBetter"], None, "NEW",
                "metric did not exist in the before run -- newly added, not comparable",
            ))
            continue
        if a is None:
            rows.append(ComparisonRow(
                category, metric_name, board, scenario, b["status"], "MISSING", b["p95"],
                None, b["unit"], b["higherIsBetter"], None, "REMOVED",
                "metric did not exist in the after run -- removed or renamed, not comparable",
            ))
            continue

        if b["status"] == "BLOCKED" or a["status"] == "BLOCKED":
            rows.append(ComparisonRow(
                category, metric_name, board, scenario, b["status"], a["status"],
                b["p95"], a["p95"], b["unit"], b["higherIsBetter"], None, "N/A",
                "at least one side is BLOCKED -- no improvement percentage computed, never fabricated",
            ))
            continue

        before_p95, after_p95 = b["p95"], a["p95"]
        higher_is_better = b["higherIsBetter"]
        if before_p95 == 0:
            improvement = None
            note = "before value is 0 -- improvement percentage undefined"
        elif higher_is_better:
            improvement = ((after_p95 - before_p95) / before_p95) * 100.0
            note = ""
        else:
            improvement = ((before_p95 - after_p95) / before_p95) * 100.0
            note = ""

        if improvement is None:
            verdict = "N/A"
        elif improvement > 0:
            verdict = "IMPROVED"
        elif improvement < 0:
            verdict = "REGRESSED"
        else:
            verdict = "UNCHANGED"

        rows.append(ComparisonRow(
            category, metric_name, board, scenario, b["status"], a["status"], before_p95,
            after_p95, b["unit"], higher_is_better, improvement, verdict, note,
        ))
    return rows


def to_markdown(rows: list[ComparisonRow], before_meta: dict, after_meta: dict) -> str:
    lines = [
        f"Before run: {before_meta.get('generatedAt', 'unknown')} ({before_meta.get('hostname', '?')})",
        f"After run:  {after_meta.get('generatedAt', 'unknown')} ({after_meta.get('hostname', '?')})",
        "",
        "| Metric | Board | Before | After | Improvement % | Verdict | Notes |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        before_str = f"{r.before_p95:.2f}{r.unit}" if r.before_p95 is not None else r.before_status
        after_str = f"{r.after_p95:.2f}{r.unit}" if r.after_p95 is not None else r.after_status
        pct_str = f"{r.improvement_pct:+.1f}%" if r.improvement_pct is not None else "N/A"
        lines.append(f"| {r.metric_name} ({r.category}) | {r.board} | {before_str} | {after_str} | {pct_str} | {r.verdict} | {r.notes} |")

    improved = sum(1 for r in rows if r.verdict == "IMPROVED")
    regressed = sum(1 for r in rows if r.verdict == "REGRESSED")
    unchanged = sum(1 for r in rows if r.verdict == "UNCHANGED")
    not_applicable = sum(1 for r in rows if r.verdict in ("N/A", "NEW", "REMOVED"))
    lines.insert(2, f"Summary: {improved} improved, {regressed} regressed, {unchanged} unchanged, {not_applicable} not comparable\n")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if not args.before.is_file():
        print(f"BLOCKED: before file not found: {args.before}")
        return 1
    if not args.after.is_file():
        print(f"BLOCKED: after file not found: {args.after}")
        return 1

    before = json.loads(args.before.read_text(encoding="utf-8"))
    after = json.loads(args.after.read_text(encoding="utf-8"))
    rows = compare(before, after)
    markdown = to_markdown(rows, before, after)

    print(markdown)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(markdown, encoding="utf-8")
        print(f"\nWritten to {args.out}")

    regressions = [r for r in rows if r.verdict == "REGRESSED"]
    if regressions:
        print(f"\n{len(regressions)} REGRESSION(S) found -- do not hide these.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
