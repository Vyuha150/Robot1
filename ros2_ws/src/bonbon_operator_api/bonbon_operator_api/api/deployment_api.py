"""Deployment + AI-runtime + Pi-efficiency API — makes the two Raspberry Pi
blockers (duplicate safety supervisor, no-Hailo) measurable and actionable
from the dashboard.

Every endpoint reads REAL data — the boot-topology verdict written by
scripts/validate_boot_topology.py, the runtime mapping in
config/runtime/model_runtime.yaml, the Pi efficiency profile, and the live
RuntimeSelector — or honestly reports it unavailable. None hardcode PASS.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, Request

from bonbon_operator_api.auth.dependencies import require_permission
from bonbon_operator_api.models.auth_models import TokenPayload
from bonbon_operator_api.models.response_models import APIResponse

logger = logging.getLogger(__name__)

deployment_router = APIRouter(tags=["deployment"])

_VALID_MODES = {"monolithic", "modular_pi"}


def _status_dir(request: Request) -> Path:
    return request.app.state.cfg.project_status_dir


def _repo_root(request: Request) -> Path:
    # project_status_dir defaults to "devops"; the repo root is its parent.
    return _status_dir(request).resolve().parent


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("deployment_api: failed to read %s: %s", path, exc)
        return None


def _read_yaml(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("deployment_api: failed to read %s: %s", path, exc)
        return None


# ── Boot topology ────────────────────────────────────────────────────────────


@deployment_router.get("/deployment/boot-topology", response_model=APIResponse)
async def boot_topology(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Current boot-topology verdict (mode, duplicate-safety flag, remediation)
    as written by scripts/validate_boot_topology.py."""
    data = _read_json(_status_dir(request) / "project-status" / "boot_topology.json")
    if data is None:
        return APIResponse.ok(
            {
                "available": False,
                "message": "No boot_topology.json — run "
                "`python3 scripts/validate_boot_topology.py` on the host.",
            }
        )
    return APIResponse.ok({"available": True, **data})


@deployment_router.get("/deployment/duplicate-node-check", response_model=APIResponse)
async def duplicate_node_check(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Whether a duplicate safety supervisor is detected. Uses the
    boot-topology verdict's observed count when present; otherwise points at
    the runtime check (which needs a sourced ROS2 workspace on the robot)."""
    data = _read_json(_status_dir(request) / "project-status" / "boot_topology.json")
    if data is None:
        return APIResponse.ok(
            {
                "available": False,
                "duplicate_safety_detected": None,
                "message": "Run `bash scripts/check_duplicate_ros_nodes.sh` on the robot.",
            }
        )
    return APIResponse.ok(
        {
            "available": True,
            "duplicate_safety_detected": data.get("duplicate_safety_detected"),
            "observed_safety_supervisors": data.get("observed_safety_supervisors"),
            "expected_safety_supervisors": data.get("expected_safety_supervisors"),
            "remediation": data.get("remediation", ""),
        }
    )


@deployment_router.post("/deployment/select-mode", response_model=APIResponse)
async def select_mode(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("config:write:critical")),
) -> APIResponse:
    """Return the exact host command to switch deployment mode. The API does
    NOT run `sudo systemctl` itself — switching the safety-supervisor boot
    topology is a privileged host action an operator runs deliberately, not
    something the dashboard backend should execute from a container."""
    body = await request.json()
    mode = str(body.get("mode", "")).strip()
    if mode not in _VALID_MODES:
        return APIResponse.ok(
            {
                "accepted": False,
                "message": f"mode must be one of {sorted(_VALID_MODES)}",
            }
        )
    return APIResponse.ok(
        {
            "accepted": True,
            "mode": mode,
            "run_on_host": f"sudo bash scripts/select_deployment_mode.sh {mode}",
            "note": "Run on the robot host; it disables the conflicting set, "
            "enables the chosen mode, and re-validates the topology.",
        }
    )


# ── AI runtime ───────────────────────────────────────────────────────────────


def _select_runtime(request: Request):
    """Lazy-import bonbon_ai_runtime and run a selection from the configured
    model_runtime.yaml. Returns (selection_dict | None, error | None)."""
    try:
        from bonbon_ai_runtime import RuntimeKind, RuntimeMode, RuntimeSelector, RuntimeSpec
    except ImportError as exc:
        return None, f"bonbon_ai_runtime not importable: {exc}"

    cfg = _read_yaml(_repo_root(request) / "config" / "runtime" / "model_runtime.yaml") or {}
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
    return result, None


@deployment_router.get("/ai-runtime/status", response_model=APIResponse)
async def ai_runtime_status(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Selected runtime, Hailo detection, fallback state + reason, and health.
    Honest: on a dev machine with no accelerator this reports a mock/cpu
    fallback with the real reason, never a fake Hailo PASS."""
    result, err = _select_runtime(request)
    if err:
        return APIResponse.ok({"available": False, "message": err})
    health = result.runtime.health()
    return APIResponse.ok(
        {
            "available": True,
            **result.to_dict(),
            "health_status": health.status.value,
            "last_latency_ms": health.last_latency_ms,
        }
    )


@deployment_router.get("/ai-runtime/models", response_model=APIResponse)
async def ai_runtime_models(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """The configured model→runtime mapping."""
    cfg = _read_yaml(_repo_root(request) / "config" / "runtime" / "model_runtime.yaml")
    if cfg is None:
        return APIResponse.ok({"available": False, "message": "model_runtime.yaml not found"})
    return APIResponse.ok(
        {"available": True, "runtime": cfg.get("runtime", {}), "models": cfg.get("models", {})}
    )


@deployment_router.get("/ai-runtime/benchmark", response_model=APIResponse)
async def ai_runtime_benchmark(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Quick benchmark of the selected runtime. On dev this benchmarks the
    mock/cpu fallback — the selected_kind tells you which, so a mock result is
    never mistaken for a Hailo PASS."""
    result, err = _select_runtime(request)
    if err:
        return APIResponse.ok({"available": False, "message": err})
    runtime = result.runtime
    runtime.warmup(runs=2)
    bench = runtime.benchmark(runs=20)
    return APIResponse.ok(
        {
            "available": True,
            "selected_kind": result.selected_kind.value,
            "fallback_active": result.fallback_active,
            "mean_ms": round(bench.mean_ms, 2),
            "p95_ms": round(bench.p95_ms, 2),
            "fps": round(bench.fps, 1),
            "failures": bench.failures,
            "is_real_accelerator": result.selected_kind.value in ("hailo", "tensorrt"),
        }
    )


# ── Pi efficiency ────────────────────────────────────────────────────────────


@deployment_router.get("/pi/efficiency", response_model=APIResponse)
async def pi_efficiency(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Pi efficiency profile (priority order, FPS limits) + live CPU/memory/
    temperature/throttle from the status aggregator's performance snapshot."""
    cfg = _read_yaml(_repo_root(request) / "config" / "pi_efficiency_profile.yaml")
    perf = request.app.state.status_aggregator.get_status().performance.model_dump()
    if cfg is None:
        return APIResponse.ok(
            {"available": False, "message": "pi_efficiency_profile.yaml not found", "live": perf}
        )
    return APIResponse.ok(
        {
            "available": True,
            "fps_limits": cfg.get("fps_limits", {}),
            "priority_order": cfg.get("priority_order", []),
            "queue_limits": cfg.get("queue_limits", {}),
            "live": perf,
        }
    )


@deployment_router.get("/pi/degraded-mode", response_model=APIResponse)
async def pi_degraded_mode(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Degraded-mode policy (what's shed, what's never disabled) + live
    degraded flag from the performance snapshot."""
    cfg = _read_yaml(_repo_root(request) / "config" / "runtime" / "degraded_mode.yaml")
    perf = request.app.state.status_aggregator.get_status().performance.model_dump()
    policy = (cfg or {}).get("degraded_mode", {})
    return APIResponse.ok(
        {
            "available": cfg is not None,
            "degraded_mode_active": perf.get("degraded_mode_active", False),
            "shed_order": policy.get("shed_order", []),
            "never_disable": policy.get("never_disable", []),
            "live_load_level": perf.get("load_level", "unknown"),
        }
    )
