"""Periodic snapshot builders for the 5 finalization-mode WebSocket
channels (boot-topology, ai-runtime, pi-efficiency, validation,
deployment-readiness).

Each function returns the same payload shape as its REST counterpart in
api/deployment_api.py / api/validation_api.py -- these are read-only
snapshots of the same real files/stores those endpoints read, not a
second data path. Kept as standalone `app`-based functions (rather than
reusing the `Request`-based REST helpers directly) because a background
asyncio task has no `Request` object to pass, only the app instance.
"""

from __future__ import annotations

import json
import logging
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[5]
for _extra in (
    _REPO_ROOT,
    _REPO_ROOT / "tests" / "scenarios",
    _REPO_ROOT / "ros2_ws" / "src" / "bonbon_ai_runtime",
):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))


def _status_dir(app: FastAPI) -> Path:
    return app.state.cfg.project_status_dir


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("status_broadcasters: failed to read %s: %s", path, exc)
        return None


def _read_yaml(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("status_broadcasters: failed to read %s: %s", path, exc)
        return None


def boot_topology_snapshot(app: FastAPI) -> dict[str, Any]:
    data = _read_json(_status_dir(app) / "project-status" / "boot_topology.json")
    if data is None:
        return {
            "available": False,
            "message": "No boot_topology.json — run scripts/validate_boot_topology.py.",
        }
    return {"available": True, **data}


def ai_runtime_snapshot(app: FastAPI) -> dict[str, Any]:
    try:
        from bonbon_ai_runtime import RuntimeKind, RuntimeMode, RuntimeSelector, RuntimeSpec
    except ImportError as exc:
        return {"available": False, "message": f"bonbon_ai_runtime not importable: {exc}"}

    cfg = _read_yaml(_REPO_ROOT / "config" / "runtime" / "model_runtime.yaml") or {}
    mode = cfg.get("runtime", {}).get("mode", "auto")
    obj = cfg.get("models", {}).get("object_detection", {})
    spec = RuntimeSpec(
        mode=RuntimeMode(mode),
        runtime_priority=[
            RuntimeKind(k) for k in obj.get("runtime_priority", ["hailo", "cpu", "mock"])
        ],
        model_paths={
            RuntimeKind.HAILO: obj.get("hailo_hef_path", ""),
            RuntimeKind.CPU: obj.get("cpu_onnx_path", ""),
        },
    )
    result = RuntimeSelector().select(spec)
    return {"available": True, **result.to_dict()}


def pi_efficiency_snapshot(app: FastAPI) -> dict[str, Any]:
    cfg = _read_yaml(_REPO_ROOT / "config" / "pi_efficiency_profile.yaml")
    perf = app.state.status_aggregator.get_status().performance.model_dump()
    if cfg is None:
        return {"available": False, "message": "pi_efficiency_profile.yaml not found", "live": perf}
    return {
        "available": True,
        "fps_limits": cfg.get("fps_limits", {}),
        "priority_order": cfg.get("priority_order", []),
        "live": perf,
    }


def validation_snapshot(app: FastAPI) -> dict[str, Any]:
    manifest = _read_yaml(
        _REPO_ROOT / "tests" / "scenarios" / "generated_scenarios" / "MANIFEST.yaml"
    )
    test_results_path = _status_dir(app) / "project-status" / "production_test_results.xml"
    test_summary: dict[str, Any] | None = None
    if test_results_path.is_file():
        try:
            root = ET.parse(test_results_path).getroot()
            suite = root.find("testsuite") if root.tag == "testsuites" else root
            if suite is not None:
                test_summary = {
                    "total": int(suite.get("tests", 0)),
                    "failed": int(suite.get("failures", 0)) + int(suite.get("errors", 0)),
                    "skipped": int(suite.get("skipped", 0)),
                }
        except ET.ParseError as exc:
            logger.warning("status_broadcasters: failed to parse test results: %s", exc)
    return {
        "available": manifest is not None,
        "total_scenarios": (manifest or {}).get("total_scenarios", 0),
        "scenarios_per_family": (manifest or {}).get("scenarios_per_family", {}),
        "last_test_summary": test_summary,
    }


def _distributed_snapshot(app: FastAPI) -> dict[str, Any]:
    bridge = app.state.ros2_bridge
    snap = bridge.get_distributed_snapshot()
    # pi1 is this Pi -- reachability is trivial (if this endpoint answered,
    # Pi-1 is up) and not tracked via the peer-heartbeat mechanism; see
    # bonbon_operator_api/ros2/distributed_status_tracker.py.
    peer_links = {k: v for k, v in snap["pi_links"].items() if k != "pi1"}
    return {**snap, "pi_links": peer_links}


def distributed_status_snapshot(app: FastAPI) -> dict[str, Any]:
    network = _read_yaml(_REPO_ROOT / "config" / "distributed" / "robot_network.yaml") or {}
    return {
        "available": bool(network),
        "deployment_mode": network.get("deployment_mode", "unknown"),
        **_distributed_snapshot(app),
    }


def pi_status_snapshot(pi_id: str):
    def _build(app: FastAPI) -> dict[str, Any]:
        snap = _distributed_snapshot(app)
        return {
            "pi_id": pi_id,
            "link_state": snap["pi_links"].get(pi_id, "unknown"),
            "bridge_ready": snap["bridge_ready"],
        }

    return _build


def pi1_status_snapshot(app: FastAPI) -> dict[str, Any]:
    # Pi-1's own liveness is trivial: if this handler ran, Pi-1 is up. It is
    # not tracked via the peer-heartbeat mechanism used for pi2/pi3 (a
    # process cannot meaningfully await its own heartbeat).
    return {"pi_id": "pi1", "link_state": "online", "bridge_ready": True}


def safety_approvals_snapshot(app: FastAPI) -> dict[str, Any]:
    snap = _distributed_snapshot(app)
    return {"last_approval": snap["last_approval"], "approval_count": snap["approval_count"]}


def safety_rejections_snapshot(app: FastAPI) -> dict[str, Any]:
    snap = _distributed_snapshot(app)
    return {"last_rejection": snap["last_rejection"], "rejection_count": snap["rejection_count"]}


def degraded_mode_snapshot(app: FastAPI) -> dict[str, Any]:
    snap = _distributed_snapshot(app)
    return snap["last_degraded_mode"] or {"is_degraded": False, "reason": "no data received yet"}


def component_health_snapshot(app: FastAPI) -> dict[str, Any]:
    status = app.state.status_aggregator.get_status()
    return {"modules": {k: v.model_dump() for k, v in status.modules.items()}}


def deployment_readiness_snapshot(app: FastAPI) -> dict[str, Any]:
    status_dir = _status_dir(app)
    issues_data = _read_json(status_dir / "project-status" / "known_issues.json")
    issues = issues_data.get("issues", []) if issues_data else []
    blocking_issues = [i for i in issues if i.get("blocking_deployment") is True]

    aggregator = app.state.status_aggregator
    status = aggregator.get_status()

    reasons: list[str] = []
    if blocking_issues:
        reasons.append(f"{len(blocking_issues)} known blocking issue(s) unresolved")
    if status.safety.state in ("fault", "safe_stop"):
        reasons.append(f"safety state is '{status.safety.state}'")
    if not status.is_online:
        reasons.append("robot is not currently connected to the dashboard")

    return {
        "ready": len(reasons) == 0,
        "reasons": reasons,
        "blocking_issue_count": len(blocking_issues),
        "robot_online": status.is_online,
        "safety_state": status.safety.state,
    }


# channel name -> snapshot builder, consumed by main.py's periodic broadcaster
CHANNEL_SNAPSHOTS = {
    "boot-topology": boot_topology_snapshot,
    "ai-runtime": ai_runtime_snapshot,
    "pi-efficiency": pi_efficiency_snapshot,
    "validation": validation_snapshot,
    "deployment-readiness": deployment_readiness_snapshot,
    # Three-Pi distributed channels
    "distributed-status": distributed_status_snapshot,
    "pi1-status": pi1_status_snapshot,
    "pi2-status": pi_status_snapshot("pi2"),
    "pi3-status": pi_status_snapshot("pi3"),
    "safety-approvals": safety_approvals_snapshot,
    "safety-rejections": safety_rejections_snapshot,
    "degraded-mode": degraded_mode_snapshot,
    "component-health": component_health_snapshot,
}
