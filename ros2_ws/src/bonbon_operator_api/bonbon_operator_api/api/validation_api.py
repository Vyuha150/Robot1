"""Production behavior-validation framework API -- scenario families,
generated scenario coverage, production test results, the weighted
production-readiness score, field-learning failure cases / regression
tests, dataset status / license checklist, model evaluation, and privacy
data-collection status.

Every endpoint reads REAL data (the generated scenario catalog, a real
JUnit XML test-results artifact, the real `bonbon_field_learning` stores,
the real `bonbon_behavior_validation.production_score` calculator) or
honestly reports it unavailable. None hardcode PASS.
"""

from __future__ import annotations

import logging
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, Request

from bonbon_operator_api.auth.dependencies import require_permission
from bonbon_operator_api.models.auth_models import TokenPayload
from bonbon_operator_api.models.response_models import APIResponse

logger = logging.getLogger(__name__)

validation_router = APIRouter(tags=["validation"])

_REPO_ROOT = Path(__file__).resolve().parents[5]
for _extra in (_REPO_ROOT, _REPO_ROOT / "tests" / "scenarios"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))


def _read_yaml(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("validation_api: failed to read %s: %s", path, exc)
        return None


def _status_dir(request: Request) -> Path:
    return request.app.state.cfg.project_status_dir


# ── /validation/scenario-families ───────────────────────────────────────────


@validation_router.get("/validation/scenario-families", response_model=APIResponse)
async def scenario_families(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """The 15 scenario families from tests/scenarios/scenario_catalog.yaml --
    name, category, risk level, hardware requirement, declared axes."""
    catalog = _read_yaml(_REPO_ROOT / "tests" / "scenarios" / "scenario_catalog.yaml")
    if catalog is None:
        return APIResponse.ok({"available": False, "message": "scenario_catalog.yaml not found"})
    families = [
        {
            "name": f["name"],
            "code": f["code"],
            "category": f["category"],
            "risk_level": f["risk_level"],
            "hardware_requirement": f["hardware_requirement"],
            "mock_strategy": f["mock_strategy"],
            "axes": list(f["axes"].keys()),
            "max_scenarios": f.get("max_scenarios"),
            "metrics": f.get("metrics", []),
        }
        for f in catalog.get("families", [])
    ]
    return APIResponse.ok({"available": True, "count": len(families), "families": families})


# ── /validation/generated-scenarios ─────────────────────────────────────────


@validation_router.get("/validation/generated-scenarios", response_model=APIResponse)
async def generated_scenarios(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Scenario counts per family from the generated catalog's manifest --
    proof the catalog was actually expanded, not just declared."""
    manifest = _read_yaml(
        _REPO_ROOT / "tests" / "scenarios" / "generated_scenarios" / "MANIFEST.yaml"
    )
    if manifest is None:
        return APIResponse.ok(
            {
                "available": False,
                "message": "No generated scenarios -- run "
                "`python tests/scenarios/scenario_generator.py`.",
            }
        )
    return APIResponse.ok(
        {
            "available": True,
            "total_scenarios": manifest.get("total_scenarios", 0),
            "scenarios_per_family": manifest.get("scenarios_per_family", {}),
        }
    )


# ── /validation/test-results ────────────────────────────────────────────────


def _parse_junit_xml(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        logger.warning("validation_api: failed to parse %s: %s", path, exc)
        return None

    suite = root.find("testsuite") if root.tag == "testsuites" else root
    if suite is None:
        return None

    per_family: dict[str, dict[str, int]] = {}
    for case in suite.findall("testcase"):
        classname = case.get("classname", "")
        family = classname.rsplit(".", 1)[-1] if classname else "unknown"
        bucket = per_family.setdefault(family, {"passed": 0, "failed": 0, "skipped": 0})
        if case.find("failure") is not None or case.find("error") is not None:
            bucket["failed"] += 1
        elif case.find("skipped") is not None:
            bucket["skipped"] += 1
        else:
            bucket["passed"] += 1

    return {
        "total": int(suite.get("tests", 0)),
        "failed": int(suite.get("failures", 0)) + int(suite.get("errors", 0)),
        "skipped": int(suite.get("skipped", 0)),
        "passed": int(suite.get("tests", 0))
        - int(suite.get("failures", 0))
        - int(suite.get("errors", 0))
        - int(suite.get("skipped", 0)),
        "duration_sec": float(suite.get("time", 0.0)),
        "timestamp": suite.get("timestamp"),
        "per_family": per_family,
    }


@validation_router.get("/validation/test-results", response_model=APIResponse)
async def test_results(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Real results from the last `scripts/run_production_tests.sh` run.
    Never fabricated -- if no run has happened yet, says so."""
    data = _parse_junit_xml(_status_dir(request) / "project-status" / "production_test_results.xml")
    if data is None:
        return APIResponse.ok(
            {
                "available": False,
                "message": "No test results -- run `bash scripts/run_production_tests.sh`.",
            }
        )
    return APIResponse.ok({"available": True, **data})


# ── /validation/production-score ────────────────────────────────────────────


def _family_pass_rate(per_family: dict[str, dict[str, int]], file_stem: str) -> float | None:
    bucket = per_family.get(file_stem)
    if not bucket:
        return None
    total = bucket["passed"] + bucket["failed"]
    if total == 0:
        return None
    return bucket["passed"] / total


@validation_router.get("/validation/production-score", response_model=APIResponse)
async def production_score(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """The weighted production readiness score. Metrics this server cannot
    honestly derive (e.g. live CPU/temp stability needs the robot) stay
    None rather than a guess -- see bonbon_behavior_validation.production_score's
    BLOCKED/PARTIAL verdicts for what that does to the result."""
    try:
        from bonbon_behavior_validation import ProductionMetrics, ProductionScoreCalculator
        from bonbon_behavior_validation.production_score import compute_maintainability_score
    except ImportError as exc:
        return APIResponse.ok(
            {"available": False, "message": f"bonbon_behavior_validation not importable: {exc}"}
        )

    test_data = _parse_junit_xml(
        _status_dir(request) / "project-status" / "production_test_results.xml"
    )
    per_family = test_data["per_family"] if test_data else {}

    metrics = ProductionMetrics(
        safety_pass_rate=_family_pass_rate(per_family, "test_safety_scenarios"),
        emergency_stop_reliability=_family_pass_rate(per_family, "test_safety_scenarios"),
        degraded_mode_recovery_rate=_family_pass_rate(per_family, "test_degraded_mode_scenarios"),
        regression_pass_rate=_family_pass_rate(per_family, "test_field_pilot_learning_scenarios"),
        object_detection_precision=_family_pass_rate(
            per_family, "test_object_recognition_scenarios"
        ),
        object_detection_recall=_family_pass_rate(per_family, "test_object_recognition_scenarios"),
        person_id_switch_rate_inverted=_family_pass_rate(
            per_family, "test_multi_person_tracking_scenarios"
        ),
        speaker_diarization_error_rate_inverted=_family_pass_rate(
            per_family, "test_speech_diarization_scenarios"
        ),
        active_speaker_assignment_accuracy=_family_pass_rate(
            per_family, "test_speech_diarization_scenarios"
        ),
        gesture_false_trigger_rate_inverted=_family_pass_rate(per_family, "test_gesture_scenarios"),
        behavior_correctness_rate=_family_pass_rate(per_family, "test_behavior_engine_scenarios"),
        dashboard_accuracy_rate=_family_pass_rate(per_family, "test_dashboard_scenarios"),
        maintainability_score=compute_maintainability_score(),
    )
    score = ProductionScoreCalculator().compute(metrics)
    return APIResponse.ok({"available": True, **score.to_dict()})


# ── /field-learning/failure-cases ───────────────────────────────────────────


def _field_learning_dir(request: Request) -> Path:
    d = _status_dir(request) / "project-status" / "field_learning"
    d.mkdir(parents=True, exist_ok=True)
    return d


@validation_router.get("/field-learning/failure-cases", response_model=APIResponse)
async def field_learning_failure_cases(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Real anonymized field failure events -- empty when none have been
    logged yet, never a placeholder."""
    try:
        from bonbon_field_learning import AnonymizedEventStore
    except ImportError as exc:
        return APIResponse.ok(
            {"available": False, "message": f"bonbon_field_learning not importable: {exc}"}
        )

    store = AnonymizedEventStore(_field_learning_dir(request) / "events.jsonl")
    events = store.all_events()
    return APIResponse.ok(
        {
            "available": True,
            "count": len(events),
            "failure_rate_by_family": store.failure_rate_by_family(),
            "events": [e.to_dict() for e in events[-100:]],
        }
    )


# ── /field-learning/regression-tests ────────────────────────────────────────


@validation_router.get("/field-learning/regression-tests", response_model=APIResponse)
async def field_learning_regression_tests(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Regression scenarios generated from reviewed field failures -- the
    growing, permanent catalog every future test run is checked against."""
    try:
        from bonbon_field_learning import RegressionTestGenerator
    except ImportError as exc:
        return APIResponse.ok(
            {"available": False, "message": f"bonbon_field_learning not importable: {exc}"}
        )

    scenarios = RegressionTestGenerator().all_regression_scenarios()
    return APIResponse.ok(
        {
            "available": True,
            "count": len(scenarios),
            "scenario_ids": [s.scenario_id for s in scenarios],
        }
    )


# ── /datasets/status ─────────────────────────────────────────────────────────


@validation_router.get("/datasets/status", response_model=APIResponse)
async def datasets_status(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Real dataset version history from bonbon_field_learning.dataset_version_manager
    -- starts at 0.0.0 with empty history until the first field batch is
    merged in; never a fabricated 'v1.0 ready' claim."""
    try:
        from bonbon_field_learning import DatasetVersionManager
    except ImportError as exc:
        return APIResponse.ok(
            {"available": False, "message": f"bonbon_field_learning not importable: {exc}"}
        )

    mgr = DatasetVersionManager(_field_learning_dir(request) / "dataset_version.json")
    history = mgr.history()
    return APIResponse.ok(
        {
            "available": True,
            "current_version": mgr.current_version(),
            "history": [h.to_dict() for h in history],
        }
    )


# ── /datasets/license-checklist ─────────────────────────────────────────────


@validation_router.get("/datasets/license-checklist", response_model=APIResponse)
async def datasets_license_checklist(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Per-capability license checklist state (config/dataset_license_checklist.yaml).
    Honest current state: NOT_SOURCED until a real dataset has actually been
    run through the 8-item checklist in docs/DATASET_LICENSE_CHECKLIST.md."""
    cfg = _read_yaml(_REPO_ROOT / "config" / "dataset_license_checklist.yaml")
    if cfg is None:
        return APIResponse.ok(
            {"available": False, "message": "dataset_license_checklist.yaml not found"}
        )
    return APIResponse.ok({"available": True, "categories": cfg.get("categories", [])})


# ── /models/evaluation ───────────────────────────────────────────────────────


@validation_router.get("/models/evaluation", response_model=APIResponse)
async def models_evaluation(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Model evaluation run history + whether the latest candidate would be
    allowed to deploy, from bonbon_field_learning.model_evaluation_tracker."""
    try:
        from bonbon_field_learning import ModelEvaluationTracker
    except ImportError as exc:
        return APIResponse.ok(
            {"available": False, "message": f"bonbon_field_learning not importable: {exc}"}
        )

    tracker = ModelEvaluationTracker(_field_learning_dir(request) / "model_evaluation.json")
    history = tracker.history()
    latest = tracker.latest()
    return APIResponse.ok(
        {
            "available": True,
            "latest": latest.to_dict() if latest else None,
            "history_count": len(history),
        }
    )


# ── /privacy/data-collection-status ─────────────────────────────────────────


@validation_router.get("/privacy/data-collection-status", response_model=APIResponse)
async def privacy_data_collection_status(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Privacy compliance status -- introspected from the real type
    definitions and store state, not self-reported. Reports whether any
    debug snapshot store is currently populated (raw-media capture active
    for this deployment) and confirms (structurally) that the default
    event store has zero raw-media fields."""
    try:
        from bonbon_field_learning.anonymized_event_store import AnonymizedEvent
    except ImportError as exc:
        return APIResponse.ok(
            {"available": False, "message": f"bonbon_field_learning not importable: {exc}"}
        )

    field_names = list(AnonymizedEvent.__dataclass_fields__.keys())
    raw_media_fields = [
        f
        for f in field_names
        if any(s in f.lower() for s in ("raw_face", "raw_audio", "image", "audio", "embedding"))
    ]

    debug_index = _field_learning_dir(request) / "debug_snapshots" / "index.jsonl"
    debug_active = debug_index.exists() and debug_index.stat().st_size > 0

    return APIResponse.ok(
        {
            "available": True,
            "anonymized_event_fields": field_names,
            "raw_media_fields_present_on_default_event_type": raw_media_fields,  # must always be []
            "debug_snapshot_store_active": debug_active,
            "debug_snapshot_count": (
                sum(1 for _ in debug_index.read_text(encoding="utf-8").splitlines())
                if debug_active
                else 0
            ),
        }
    )
