"""AuthorityManager — turns HeartbeatMonitor link states into the exact
per-Pi behavior specified in config/distributed/failure_policy.yaml.

Each Pi runs its own AuthorityManager scoped to its own role — there is no
central arbiter, matching failure_policy.yaml's
`full_partition_behavior: each_pi_applies_its_own_loss_policies_independently`.
Pure Python, no rclpy dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from bonbon_distributed_safety.core.heartbeat_monitor import PiId, PiLinkState


class SelfRole(StrEnum):
    PI1_UI_API = "pi1"
    PI2_HUMAN_AI = "pi2"
    PI3_NAVIGATION_SAFETY = "pi3"


@dataclass(frozen=True)
class AuthoritySnapshot:
    self_role: SelfRole
    motion_authority_available: bool
    human_interaction_permitted: bool
    should_pause_proposals: bool
    degraded_modules: tuple[str, ...]
    dashboard_message: str
    policy_reason: str  # matches a key in failure_policy.yaml, or "nominal"


_NOMINAL_MESSAGE = "nominal — all Pis reachable"


class AuthorityManager:
    def __init__(self, self_role: SelfRole) -> None:
        self._self_role = self_role

    @property
    def self_role(self) -> SelfRole:
        return self._self_role

    def evaluate(self, link_states: dict[PiId, PiLinkState]) -> AuthoritySnapshot:
        if self._self_role == SelfRole.PI3_NAVIGATION_SAFETY:
            return self._evaluate_as_pi3(link_states)
        if self._self_role == SelfRole.PI1_UI_API:
            return self._evaluate_as_pi1(link_states)
        return self._evaluate_as_pi2(link_states)

    # ── Pi-3: sole motion authority; never depends on Pi-1/Pi-2 for its own
    #    physical safety (see FAILURE_AND_DEGRADED_MODE_POLICY.md) ────────────
    def _evaluate_as_pi3(self, link_states: dict[PiId, PiLinkState]) -> AuthoritySnapshot:
        pi2_lost = link_states.get(PiId.PI2) == PiLinkState.LOST
        if pi2_lost:
            return AuthoritySnapshot(
                self_role=self._self_role,
                motion_authority_available=True,  # Pi-3 always retains its own authority
                human_interaction_permitted=False,
                should_pause_proposals=False,  # n/a — Pi-3 doesn't emit proposals
                degraded_modules=("human_ai",),
                dashboard_message="Pi-2 unreachable — human interaction disabled, motion unaffected",
                policy_reason="pi3_loses_pi2",
            )
        return AuthoritySnapshot(
            self_role=self._self_role,
            motion_authority_available=True,
            human_interaction_permitted=True,
            should_pause_proposals=False,
            degraded_modules=(),
            dashboard_message=_NOMINAL_MESSAGE,
            policy_reason="nominal",
        )

    # ── Pi-1: dashboard/operator; motion authority tracks Pi-3 reachability ──
    def _evaluate_as_pi1(self, link_states: dict[PiId, PiLinkState]) -> AuthoritySnapshot:
        pi3_lost = link_states.get(PiId.PI3) == PiLinkState.LOST
        if pi3_lost:
            return AuthoritySnapshot(
                self_role=self._self_role,
                motion_authority_available=False,
                human_interaction_permitted=True,  # not pi1's concern to gate
                should_pause_proposals=False,
                degraded_modules=("navigation_safety",),
                dashboard_message="Motion authority unavailable — Pi-3 unreachable",
                policy_reason="pi1_loses_pi3",
            )
        return AuthoritySnapshot(
            self_role=self._self_role,
            motion_authority_available=True,
            human_interaction_permitted=True,
            should_pause_proposals=False,
            degraded_modules=(),
            dashboard_message=_NOMINAL_MESSAGE,
            policy_reason="nominal",
        )

    # ── Pi-2: perception/LLM; pauses proposal emission when Pi-3 is gone ─────
    def _evaluate_as_pi2(self, link_states: dict[PiId, PiLinkState]) -> AuthoritySnapshot:
        pi3_lost = link_states.get(PiId.PI3) == PiLinkState.LOST
        if pi3_lost:
            return AuthoritySnapshot(
                self_role=self._self_role,
                motion_authority_available=False,  # informational only, Pi-2 has none anyway
                human_interaction_permitted=True,  # local perception/ASR/LLM keep running
                should_pause_proposals=True,
                degraded_modules=("navigation_safety",),
                dashboard_message="Pi-3 unreachable — behavior proposals paused",
                policy_reason="pi2_loses_pi3",
            )
        return AuthoritySnapshot(
            self_role=self._self_role,
            motion_authority_available=True,
            human_interaction_permitted=True,
            should_pause_proposals=False,
            degraded_modules=(),
            dashboard_message=_NOMINAL_MESSAGE,
            policy_reason="nominal",
        )
