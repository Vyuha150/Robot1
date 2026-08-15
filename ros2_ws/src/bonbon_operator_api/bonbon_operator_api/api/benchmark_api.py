"""Efficiency benchmarking dashboard API (Phase 14).

Every endpoint reads REAL data from bonbon_benchmarks' persisted results
(docs/project-status/efficiency_benchmark_results.json /
efficiency_benchmark_history.json) or honestly reports it unavailable --
POST /benchmarks/run actually executes bonbon_benchmarks.benchmark_runner,
it does not return a canned response.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from bonbon_operator_api.auth.dependencies import require_permission
from bonbon_operator_api.models.auth_models import TokenPayload
from bonbon_operator_api.models.response_models import APIResponse

logger = logging.getLogger(__name__)

benchmark_router = APIRouter(tags=["benchmarks"])

_REPO_ROOT = Path(__file__).resolve().parents[5]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_PRODUCTION_THRESHOLDS_PATH = _REPO_ROOT / "config" / "benchmarks" / "production_acceptance_thresholds.yaml"
_EDGE_AI_RESULTS_PATH = _REPO_ROOT / "docs" / "project-status" / "edge_ai_benchmark_results.json"


def _status_dir(request: Request) -> Path:
    return request.app.state.cfg.project_status_dir


def _results_path(request: Request) -> Path:
    return _status_dir(request) / "project-status" / "efficiency_benchmark_results.json"


def _history_path(request: Request) -> Path:
    return _status_dir(request) / "project-status" / "efficiency_benchmark_history.json"


# ── GET /benchmarks/status ────────────────────────────────────────────────


@benchmark_router.get("/benchmarks/status", response_model=APIResponse)
async def benchmarks_status(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Whether a benchmark run has ever completed, and its top-line summary."""
    try:
        from bonbon_benchmarks.benchmark_reporter import load
    except ImportError as exc:
        return APIResponse.ok({"available": False, "message": f"bonbon_benchmarks not importable: {exc}"})

    data = load(_results_path(request))
    if data is None:
        return APIResponse.ok({"available": False, "message": "no benchmark run has completed yet -- POST /benchmarks/run"})
    return APIResponse.ok({
        "available": True,
        "generatedAt": data["generatedAt"],
        "hostname": data["hostname"],
        "summary": data["summary"],
        "categoriesRun": [c["category"] for c in data["categories"]],
    })


# ── GET /benchmarks/latest ────────────────────────────────────────────────


@benchmark_router.get("/benchmarks/latest", response_model=APIResponse)
async def benchmarks_latest(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Full latest run detail -- every metric, every category."""
    try:
        from bonbon_benchmarks.benchmark_reporter import load
    except ImportError as exc:
        return APIResponse.ok({"available": False, "message": f"bonbon_benchmarks not importable: {exc}"})

    data = load(_results_path(request))
    if data is None:
        return APIResponse.ok({"available": False, "message": "no benchmark run has completed yet"})
    return APIResponse.ok({"available": True, **data})


# ── GET /benchmarks/history ───────────────────────────────────────────────


@benchmark_router.get("/benchmarks/history", response_model=APIResponse)
async def benchmarks_history(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Bounded run history (summaries only, not full per-metric detail)."""
    try:
        from bonbon_benchmarks.benchmark_reporter import load_history
    except ImportError as exc:
        return APIResponse.ok({"available": False, "message": f"bonbon_benchmarks not importable: {exc}"})

    runs = load_history(_history_path(request))
    return APIResponse.ok({"available": True, "count": len(runs), "runs": runs})


# ── POST /benchmarks/run ──────────────────────────────────────────────────


class RunBenchmarksRequest(BaseModel):
    categories: list[str] | None = None


@benchmark_router.post("/benchmarks/run", response_model=APIResponse)
async def benchmarks_run(
    request: Request,
    body: RunBenchmarksRequest,
    current_user: TokenPayload = Depends(require_permission("diagnostics:write")),
) -> APIResponse:
    """Actually executes bonbon_benchmarks.benchmark_runner.run() -- a real
    run, not a canned response. Persists results + appends to history."""
    try:
        from bonbon_benchmarks.benchmark_reporter import append_history, persist
        from bonbon_benchmarks.benchmark_runner import CATEGORY_NAMES, run
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"bonbon_benchmarks not importable: {exc}") from exc

    categories = body.categories or list(CATEGORY_NAMES)
    unknown = [c for c in categories if c not in CATEGORY_NAMES]
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown categories: {unknown}; valid: {list(CATEGORY_NAMES)}")

    try:
        result = run(categories=categories)
    except Exception as exc:  # noqa: BLE001 -- a benchmark failure must be reported honestly, not crash the endpoint
        logger.exception("benchmark run failed")
        raise HTTPException(status_code=500, detail=f"benchmark run failed: {exc}") from exc

    persist(result, _results_path(request))
    append_history(result, _history_path(request))
    return APIResponse.ok({"triggered": True, "elapsedSec": result.elapsed_sec, "summary": result.summary()})


# ── GET /benchmarks/compare ───────────────────────────────────────────────


@benchmark_router.get("/benchmarks/compare", response_model=APIResponse)
async def benchmarks_compare(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Compares the two most recent history entries' summaries. For a
    full metric-by-metric comparison against an arbitrary baseline file,
    use scripts/benchmarks/compare_benchmark_runs.py directly."""
    try:
        from bonbon_benchmarks.benchmark_reporter import load_history
    except ImportError as exc:
        return APIResponse.ok({"available": False, "message": f"bonbon_benchmarks not importable: {exc}"})

    runs = load_history(_history_path(request))
    if len(runs) < 2:
        return APIResponse.ok({
            "available": False,
            "message": f"need at least 2 completed runs to compare, have {len(runs)} -- run POST /benchmarks/run again",
        })
    previous, latest = runs[-2], runs[-1]
    return APIResponse.ok({
        "available": True,
        "previous": previous,
        "latest": latest,
        "note": "summary-level only; run scripts/benchmarks/compare_benchmark_runs.py for full per-metric detail",
    })


# ── GET /benchmarks/production-score ──────────────────────────────────────


@benchmark_router.get("/benchmarks/production-score", response_model=APIResponse)
async def benchmarks_production_score(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """A weighted verdict against config/benchmarks/production_acceptance_thresholds.yaml,
    computed from the latest real run -- never a hardcoded PASS."""
    try:
        from bonbon_benchmarks.benchmark_reporter import load
    except ImportError as exc:
        return APIResponse.ok({"available": False, "message": f"bonbon_benchmarks not importable: {exc}"})

    data = load(_results_path(request))
    if data is None:
        return APIResponse.ok({"available": False, "message": "no benchmark run has completed yet"})

    summary = data["summary"]
    total = summary["PASS"] + summary["FAIL"] + summary["BLOCKED"]
    measured = summary["PASS"] + summary["FAIL"]
    pass_rate = (summary["PASS"] / measured) if measured else None

    # Critical categories: safety_under_load must have zero FAIL among
    # its measured metrics -- a single safety regression fails the whole
    # verdict regardless of how many other categories passed.
    safety_metrics = next((c["metrics"] for c in data["categories"] if c["category"] == "safety_under_load"), [])
    safety_failures = [m for m in safety_metrics if m["status"] == "FAIL"]

    if safety_failures:
        verdict = "FAIL"
    elif pass_rate is None:
        verdict = "BLOCKED"
    elif summary["FAIL"] > 0:
        verdict = "PARTIAL"
    elif summary["BLOCKED"] > 0:
        verdict = "PARTIAL"
    else:
        verdict = "PASS"

    return APIResponse.ok({
        "available": True,
        "verdict": verdict,
        "passRate": pass_rate,
        "counts": summary,
        "totalMetrics": total,
        "safetyFailures": [m["metricName"] for m in safety_failures],
        "generatedAt": data["generatedAt"],
    })


# ── GET /benchmarks/safety-under-load ─────────────────────────────────────


@benchmark_router.get("/benchmarks/safety-under-load", response_model=APIResponse)
async def benchmarks_safety_under_load(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    try:
        from bonbon_benchmarks.benchmark_reporter import load
    except ImportError as exc:
        return APIResponse.ok({"available": False, "message": f"bonbon_benchmarks not importable: {exc}"})

    data = load(_results_path(request))
    if data is None:
        return APIResponse.ok({"available": False, "message": "no benchmark run has completed yet"})
    category = next((c for c in data["categories"] if c["category"] == "safety_under_load"), None)
    if category is None:
        return APIResponse.ok({"available": False, "message": "latest run did not include safety_under_load"})
    return APIResponse.ok({"available": True, **category})


# ── GET /benchmarks/edge-ai ────────────────────────────────────────────────


@benchmark_router.get("/benchmarks/edge-ai", response_model=APIResponse)
async def benchmarks_edge_ai(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Reuses scripts/edge_ai/benchmark_edge_ai_stack.py's own persisted
    results file (already served at GET /api/v1/edge-ai/benchmarks) --
    exposed here too under the /benchmarks/* namespace this brief
    requests, not a second benchmark run."""
    if not _EDGE_AI_RESULTS_PATH.is_file():
        return APIResponse.ok({
            "available": False,
            "message": "no edge-ai benchmark run yet -- run `python3 scripts/edge_ai/benchmark_edge_ai_stack.py`",
        })
    import json

    data = json.loads(_EDGE_AI_RESULTS_PATH.read_text(encoding="utf-8"))
    return APIResponse.ok({"available": True, **data})


# ── GET /benchmarks/three-pi ───────────────────────────────────────────────


@benchmark_router.get("/benchmarks/three-pi", response_model=APIResponse)
async def benchmarks_three_pi(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    try:
        from bonbon_benchmarks.benchmark_reporter import load
    except ImportError as exc:
        return APIResponse.ok({"available": False, "message": f"bonbon_benchmarks not importable: {exc}"})

    data = load(_results_path(request))
    if data is None:
        return APIResponse.ok({"available": False, "message": "no benchmark run has completed yet"})
    category = next((c for c in data["categories"] if c["category"] == "three_pi_network"), None)
    if category is None:
        return APIResponse.ok({"available": False, "message": "latest run did not include three_pi_network"})
    return APIResponse.ok({"available": True, **category})
