"""Renders a FullBenchmarkRun to a markdown table and persists it as JSON,
matching the existing docs/project-status/{ai_model,edge_ai}_benchmark_results.json
convention (same directory, same "generated_at/environment/results" shape)
so the dashboard's existing results-file-reading pattern extends naturally
to this suite rather than inventing a third file convention.
"""

from __future__ import annotations

import json
from pathlib import Path

from bonbon_benchmarks.benchmark_runner import FullBenchmarkRun

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_PATH = _REPO_ROOT / "docs" / "project-status" / "efficiency_benchmark_results.json"
DEFAULT_HISTORY_PATH = _REPO_ROOT / "docs" / "project-status" / "efficiency_benchmark_history.json"
_HISTORY_MAX_ENTRIES = 50


def to_markdown(run: FullBenchmarkRun) -> str:
    lines = [
        f"Generated: {run.generated_at}  |  Host: {run.hostname}  |  Platform: {run.platform_str}  |  Elapsed: {run.elapsed_sec:.1f}s",
        "",
        f"Summary: {run.summary()}",
        "",
        "| Category | Metric | Board | Module | Scenario | Avg | P50 | P90 | P95 | P99 | Max | Unit | N | Status | Blocked Reason |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for cat in run.categories:
        for m in cat.metrics:
            lines.append(
                f"| {cat.category} | {m.metric_name} | {m.board} | {m.module} | {m.scenario} | "
                f"{m.avg:.2f} | {m.p50:.2f} | {m.p90:.2f} | {m.p95:.2f} | {m.p99:.2f} | {m.max:.2f} | "
                f"{m.unit} | {m.sample_count} | {m.status} | {m.blocked_reason} |"
            )
    return "\n".join(lines)


def persist(run: FullBenchmarkRun, path: Path = DEFAULT_RESULTS_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(run.to_dict(), indent=2), encoding="utf-8")
    return path


def load(path: Path = DEFAULT_RESULTS_PATH) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def append_history(
    run: FullBenchmarkRun, path: Path = DEFAULT_HISTORY_PATH, max_entries: int = _HISTORY_MAX_ENTRIES
) -> Path:
    """Appends a compact summary (not the full per-metric detail already
    in DEFAULT_RESULTS_PATH) to a bounded history log -- real appended
    entries, capped so this file never grows unbounded across many runs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    if path.is_file():
        try:
            entries = json.loads(path.read_text(encoding="utf-8")).get("runs", [])
        except (OSError, ValueError):
            entries = []
    entries.append({
        "generatedAt": run.generated_at,
        "hostname": run.hostname,
        "elapsedSec": round(run.elapsed_sec, 2),
        "summary": run.summary(),
        "categories": [c.category for c in run.categories],
    })
    entries = entries[-max_entries:]
    path.write_text(json.dumps({"runs": entries}, indent=2), encoding="utf-8")
    return path


def load_history(path: Path = DEFAULT_HISTORY_PATH) -> list[dict]:
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("runs", [])
