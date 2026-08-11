"""MotionApprovalGateway — the sole Pi-3 authority that turns a
BehaviorProposal-shaped input into a BehaviorDecision-shaped output.

This is the pure-Python heart of the new bonbon_motion_approval_gateway
node (nodes/motion_approval_gateway_node.py), which subscribes
/bonbon/behavior/proposal + /bonbon/operator/proposal and publishes
/bonbon/safety/approval + /bonbon/safety/rejection +
/bonbon/motion/approved_command using the REAL bonbon_msgs/BehaviorProposal
and bonbon_msgs/BehaviorDecision types (see
docs/DISTRIBUTED_TOPIC_SERVICE_CONTRACT.md for why those existing,
already-registered types are reused rather than new ones invented).

Field names below mirror BehaviorProposal.msg / BehaviorDecision.msg
exactly so the node wrapper's translation to/from real ROS2 messages is a
trivial field-by-field copy, not a re-interpretation.

Safety rules encoded here (see docs/INTER_PI_COMMUNICATION_POLICY.md):
  - Rule 10: the SAME rules apply regardless of source_module. An
    'operator' proposal gets no bypass an 'llm' proposal wouldn't get.
  - Unknown proposal_type is always rejected, never passed through as if
    understood — this repo's established no-fake-PASS posture applied to
    the safety-authority boundary.
  - requires_manual_reset (FAULT/SAFE_STOP) blocks everything except
    alert_operator/ignore — the two proposal types that carry no physical
    risk even in a faulted state.
"""

from __future__ import annotations

from dataclasses import dataclass

_MOTION_TYPES = frozenset({"navigate", "approach", "retreat", "dock"})
_ACTUATION_TYPES = frozenset({"gesture"})
_ALWAYS_SAFE_TYPES = frozenset({"alert_operator", "ignore"})
_KNOWN_TYPES = (
    _MOTION_TYPES
    | _ACTUATION_TYPES
    | _ALWAYS_SAFE_TYPES
    | frozenset({"speak", "ask_clarification", "pause", "resume"})
)

_ESCALATE_URGENCY_THRESHOLD = 0.7
_ESCALATE_STATES = frozenset({"DANGER", "SAFE_STOP"})

_DECISION_APPROVED = "approved"
_DECISION_REJECTED = "rejected"
_DECISION_ESCALATED = "escalated"


@dataclass(frozen=True)
class ProposalInput:
    event_id: str
    source_module: str  # 'llm','speech_intent','gesture','rule_engine','operator'
    person_id: str
    proposal_type: str
    proposal_content: str
    urgency: float
    justification: str = ""
    safety_check_required: bool = True
    # Navigation destination, populated when proposal_type is
    # navigate/approach/retreat -- GAP-E2 fix. Previously dropped before
    # reaching evaluate() even though BehaviorProposal.msg already
    # carried nav_goal_pose/nav_goal_label, which meant an approved
    # navigation decision had no destination to act on.
    nav_goal_x: float = 0.0
    nav_goal_y: float = 0.0
    nav_goal_yaw: float = 0.0
    nav_goal_label: str = ""


@dataclass(frozen=True)
class SafetyContext:
    state_name: str  # NORMAL/CAUTION/DANGER/DOCKING/DEGRADED/FAULT/SAFE_STOP
    actuation_permitted: bool
    navigation_permitted: bool
    max_velocity_mps: float
    requires_manual_reset: bool


@dataclass(frozen=True)
class DecisionResult:
    event_id: str
    proposal_event_id: str
    decision: str  # approved/rejected/modified/deferred/escalated
    approved_action: str
    approved_content: str
    safety_approved: bool
    rejection_reason: str
    modification_note: str
    confidence: float
    operator_alerted: bool
    logged: bool
    # Only populated (non-zero/non-empty) when decision == "approved" and
    # approved_action is a motion type -- GAP-E2 fix, mirrors
    # ProposalInput's nav_goal_* fields.
    nav_goal_x: float = 0.0
    nav_goal_y: float = 0.0
    nav_goal_yaw: float = 0.0
    nav_goal_label: str = ""


class MotionApprovalGateway:
    """Stateless per-call evaluation — every proposal is judged only
    against the SafetyContext passed alongside it, never against gateway-
    internal memory of prior proposals (no hidden state that could let an
    earlier approval bleed into a later, differently-risky one)."""

    def __init__(self, event_id_factory=None) -> None:
        # Injectable for deterministic tests; defaults to a simple counter
        # scheme in the node wrapper (real UUIDs there, not needed here).
        self._event_id_factory = event_id_factory or (lambda: "decision-auto")

    def evaluate(self, proposal: ProposalInput, safety: SafetyContext) -> DecisionResult:
        if proposal.proposal_type not in _KNOWN_TYPES:
            return self._reject(
                proposal,
                reason=f"unrecognized proposal_type {proposal.proposal_type!r} — never approved silently",
            )

        if safety.requires_manual_reset and proposal.proposal_type not in _ALWAYS_SAFE_TYPES:
            return self._reject(
                proposal,
                reason=f"safety state {safety.state_name} requires manual reset before any action",
            )

        if proposal.proposal_type in _MOTION_TYPES and not safety.navigation_permitted:
            return self._reject(
                proposal,
                reason=f"navigation not permitted in safety state {safety.state_name}",
            )

        if proposal.proposal_type in _ACTUATION_TYPES and not safety.actuation_permitted:
            return self._reject(
                proposal,
                reason=f"actuation not permitted in safety state {safety.state_name}",
            )

        if (
            safety.state_name in _ESCALATE_STATES
            and proposal.urgency >= _ESCALATE_URGENCY_THRESHOLD
            and proposal.proposal_type not in _ALWAYS_SAFE_TYPES
        ):
            return self._escalate(proposal, safety)

        return self._approve(proposal, safety)

    # ── Outcome builders ──────────────────────────────────────────────────────

    def _approve(self, proposal: ProposalInput, safety: SafetyContext) -> DecisionResult:
        modification_note = ""
        approved_content = proposal.proposal_content
        if proposal.proposal_type in _MOTION_TYPES and safety.max_velocity_mps > 0:
            modification_note = (
                f"velocity capped at {safety.max_velocity_mps:.2f} m/s by safety state"
            )
        is_motion = proposal.proposal_type in _MOTION_TYPES
        return DecisionResult(
            event_id=self._event_id_factory(),
            proposal_event_id=proposal.event_id,
            decision=_DECISION_APPROVED,
            approved_action=proposal.proposal_type,
            approved_content=approved_content,
            safety_approved=True,
            rejection_reason="",
            modification_note=modification_note,
            confidence=1.0,
            operator_alerted=False,
            logged=True,
            # Destination only carried through for motion types -- a
            # non-motion approval (e.g. "speak") must never appear to
            # carry a navigation goal just because the field exists.
            nav_goal_x=proposal.nav_goal_x if is_motion else 0.0,
            nav_goal_y=proposal.nav_goal_y if is_motion else 0.0,
            nav_goal_yaw=proposal.nav_goal_yaw if is_motion else 0.0,
            nav_goal_label=proposal.nav_goal_label if is_motion else "",
        )

    def _reject(self, proposal: ProposalInput, reason: str) -> DecisionResult:
        return DecisionResult(
            event_id=self._event_id_factory(),
            proposal_event_id=proposal.event_id,
            decision=_DECISION_REJECTED,
            approved_action="",
            approved_content="",
            safety_approved=False,
            rejection_reason=reason,
            modification_note="",
            confidence=1.0,
            operator_alerted=False,
            logged=True,
        )

    def _escalate(self, proposal: ProposalInput, safety: SafetyContext) -> DecisionResult:
        return DecisionResult(
            event_id=self._event_id_factory(),
            proposal_event_id=proposal.event_id,
            decision=_DECISION_ESCALATED,
            approved_action="",
            approved_content="",
            safety_approved=False,
            rejection_reason=(
                f"urgency {proposal.urgency:.2f} in safety state {safety.state_name} "
                "requires operator escalation, not automatic approval or silent rejection"
            ),
            modification_note="",
            confidence=1.0,
            operator_alerted=True,
            logged=True,
        )
