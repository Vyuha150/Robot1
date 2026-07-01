"""Distributed (three-Pi) status API — makes Pi-1's view of Pi-2/Pi-3
liveness, the live safety-authority chain, and the static topology config
visible on the dashboard.

Every endpoint reads REAL data: config/distributed/*.yaml for static
topology, and the ROS2 bridge's DistributedStatusTracker for live
heartbeat/approval/rejection/degraded-mode state — or honestly reports it
unavailable, exactly like deployment_api.py's existing pattern. Nothing
here hardcodes a PASS or assumes Pi-2/Pi-3 are reachable.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request

from bonbon_operator_api.auth.dependencies import require_permission
from bonbon_operator_api.models.auth_models import TokenPayload
from bonbon_operator_api.models.command_models import CommandResponse, OperatorProposalCommand
from bonbon_operator_api.models.response_models import APIResponse
from bonbon_operator_api.safety.command_validator import ValidationError
from bonbon_operator_api.safety.safety_gate import SafetyGateError

logger = logging.getLogger(__name__)

distributed_router = APIRouter(tags=["distributed"])

_VALID_PIS = {"pi1", "pi2", "pi3"}
_PI_PROFILE_FILES = {
    "pi1": "pi_ui_api.yaml",
    "pi2": "pi_human_ai.yaml",
    "pi3": "pi_navigation_safety.yaml",
}


def _repo_root(request: Request) -> Path:
    return request.app.state.cfg.project_status_dir.resolve().parent


def _distributed_config_dir(request: Request) -> Path:
    return _repo_root(request) / "config" / "distributed"


def _read_yaml(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("distributed_api: failed to read %s: %s", path, exc)
        return None


# ── Live status ──────────────────────────────────────────────────────────────


@distributed_router.get("/distributed/status", response_model=APIResponse)
async def distributed_status(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Overall three-Pi status: static topology + live peer liveness."""
    network = _read_yaml(_distributed_config_dir(request) / "robot_network.yaml") or {}
    bridge = request.app.state.ros2_bridge
    snap = bridge.get_distributed_snapshot()
    peer_links = {k: v for k, v in snap["pi_links"].items() if k != "pi1"}
    return APIResponse.ok(
        {
            "available": bool(network),
            "deployment_mode": network.get("deployment_mode", "unknown"),
            "bridge_ready": snap["bridge_ready"],
            "pi_links": peer_links,
            "pis": network.get("pis", {}),
        }
    )


@distributed_router.get("/distributed/pi/{pi_id}", response_model=APIResponse)
async def distributed_pi_detail(
    pi_id: str,
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """One Pi's runtime profile (packages/services/boot order) + live link state."""
    if pi_id not in _VALID_PIS:
        raise HTTPException(status_code=404, detail=f"unknown pi_id {pi_id!r}")

    profile = _read_yaml(_distributed_config_dir(request) / _PI_PROFILE_FILES[pi_id])
    bridge = request.app.state.ros2_bridge
    snap = bridge.get_distributed_snapshot()
    link_state = "online" if pi_id == "pi1" else snap["pi_links"].get(pi_id, "unknown")

    if profile is None:
        return APIResponse.ok(
            {
                "available": False,
                "pi_id": pi_id,
                "link_state": link_state,
                "message": f"{_PI_PROFILE_FILES[pi_id]} not found",
            }
        )
    return APIResponse.ok({"available": True, "pi_id": pi_id, "link_state": link_state, **profile})


@distributed_router.get("/distributed/safety/approvals", response_model=APIResponse)
async def distributed_safety_approvals(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("robot:read")),
) -> APIResponse:
    """Most recent motion-proposal approval/rejection from Pi-3's
    motion_approval_gateway, plus running counts."""
    bridge = request.app.state.ros2_bridge
    snap = bridge.get_distributed_snapshot()
    return APIResponse.ok(
        {
            "bridge_ready": snap["bridge_ready"],
            "last_approval": snap["last_approval"],
            "last_rejection": snap["last_rejection"],
            "approval_count": snap["approval_count"],
            "rejection_count": snap["rejection_count"],
        }
    )


@distributed_router.get("/distributed/degraded-mode", response_model=APIResponse)
async def distributed_degraded_mode(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Latest fleet-wide degraded-mode reason from bonbon_authority_manager
    (Pi-3's authoritative publisher, per topic_contracts.yaml)."""
    bridge = request.app.state.ros2_bridge
    snap = bridge.get_distributed_snapshot()
    data = snap["last_degraded_mode"] or {
        "is_degraded": False,
        "reason": "no data received yet",
        "duration_sec": 0.0,
    }
    return APIResponse.ok({"bridge_ready": snap["bridge_ready"], **data})


# ── Static topology config ──────────────────────────────────────────────────


@distributed_router.get("/distributed/topology", response_model=APIResponse)
async def distributed_topology(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Static network topology: IPs, ROS_DOMAIN_ID, DDS discovery, chrony, heartbeat config."""
    network = _read_yaml(_distributed_config_dir(request) / "robot_network.yaml")
    if network is None:
        return APIResponse.ok(
            {"available": False, "message": "config/distributed/robot_network.yaml not found"}
        )
    return APIResponse.ok({"available": True, **network})


@distributed_router.get("/distributed/topics", response_model=APIResponse)
async def distributed_topics(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """The full inter-Pi topic contract table."""
    topics = _read_yaml(_distributed_config_dir(request) / "topic_contracts.yaml")
    if topics is None:
        return APIResponse.ok(
            {"available": False, "message": "config/distributed/topic_contracts.yaml not found"}
        )
    return APIResponse.ok({"available": True, **topics})


@distributed_router.get("/distributed/failure-policy", response_model=APIResponse)
async def distributed_failure_policy(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """The exact per-Pi-loss behavior policy — what each Pi does when it
    loses contact with another."""
    policy = _read_yaml(_distributed_config_dir(request) / "failure_policy.yaml")
    if policy is None:
        return APIResponse.ok(
            {"available": False, "message": "config/distributed/failure_policy.yaml not found"}
        )
    return APIResponse.ok({"available": True, **policy})


# ── Operator proposal (dashboard's ONLY way to request movement) ────────────


@distributed_router.post("/distributed/operator-proposal", response_model=APIResponse)
async def submit_operator_proposal(
    request: Request,
    body: OperatorProposalCommand,
    current_user: TokenPayload = Depends(require_permission("robot:command:navigate")),
) -> APIResponse:
    """Publish an operator-sourced BehaviorProposal to /bonbon/operator/proposal.

    This is deliberately NOT a command endpoint — the response confirms the
    proposal was SENT, never that it was approved. Pi-3's
    motion_approval_gateway makes that call, applying the exact same rules
    to this proposal as to any AI-originated one (see
    docs/INTER_PI_COMMUNICATION_POLICY.md Rule 5 and Rule 10). Gated
    through the same SafetyCommandGate every other dashboard command uses,
    as a local advisory pre-filter -- never a substitute for Pi-3's
    validation.
    """
    command_id = str(uuid.uuid4())
    metrics = request.app.state.metrics
    gate = request.app.state.safety_gate
    ip = request.client.host if request.client else ""

    with metrics.time_command("operator_proposal"):
        try:
            gate.check_and_validate(
                command_type="operator_proposal",
                payload=body,
                command_id=command_id,
                actor_id=current_user.sub,
                actor_name=current_user.username,
                actor_role=current_user.role,
                ip_address=ip,
            )
        except ValidationError as exc:
            metrics.record_command("operator_proposal", "validation_error")
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except SafetyGateError as exc:
            code = getattr(exc, "code", "SAFETY_GATE_REJECTED")
            status_code = 409 if code == "DUPLICATE_COMMAND" else 503
            metrics.record_command(
                "operator_proposal",
                "duplicate" if code == "DUPLICATE_COMMAND" else "safety_blocked",
            )
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

        bridge = request.app.state.ros2_bridge
        result = bridge.call_operator_proposal(
            proposal_type=body.proposal_type,
            proposal_content=body.proposal_content,
            urgency=body.urgency,
            justification=body.justification,
            person_id=body.person_id,
        )
        if result.get("success") is False:
            metrics.record_command("operator_proposal", "dispatch_failed")
            detail = result.get("message") or result.get("error") or "proposal dispatch failed"
            raise HTTPException(status_code=503, detail=detail)

    metrics.record_command("operator_proposal", "accepted")
    return APIResponse.ok(
        CommandResponse(
            accepted=True,
            command_id=command_id,
            message=result.get("note") or "Proposal sent to Pi-3 for safety validation",
            queued_at=time.time(),
        )
    )
