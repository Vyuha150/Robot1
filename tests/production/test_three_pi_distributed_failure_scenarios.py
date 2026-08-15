"""3-Pi distributed failure scenarios (3-Pi Phase 12).

Confirmed via audit: no distributed-systems-focused test suite existed
anywhere in this repo -- the 15-family behavior-scenario suite covers
single-Pi safety/perception/navigation behavior, not multi-Pi failure
propagation (Pi-down, network partition, flapping links, recovery timing).

This suite combines the REAL, already-tested primitives
(bonbon_distributed_safety.core.heartbeat_monitor.HeartbeatMonitor,
bonbon_distributed_safety.core.flap_detector.FlapDetector,
bonbon_authority_manager.core.authority_manager.AuthorityManager) in
realistic multi-step, multi-Pi-perspective timelines, cross-checked
against config/distributed/failure_policy.yaml's documented behavior for
every pairwise loss scenario -- not mocks, not a re-implementation of the
policy, the actual classes that would run on real hardware.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(
    0, str(_REPO_ROOT / "ros2_ws" / "src" / "bonbon_distributed_safety")
)
sys.path.insert(
    0, str(_REPO_ROOT / "ros2_ws" / "src" / "bonbon_authority_manager")
)

from bonbon_authority_manager.core.authority_manager import (  # noqa: E402
    AuthorityManager,
    SelfRole,
)
from bonbon_distributed_safety.core.flap_detector import (  # noqa: E402
    FlapConfig,
    FlapDetector,
)
from bonbon_distributed_safety.core.heartbeat_monitor import (  # noqa: E402
    HeartbeatConfig,
    HeartbeatMonitor,
    PiId,
    PiLinkState,
)

pytestmark = [pytest.mark.integration, pytest.mark.safety]

# Real values from config/distributed/robot_network.yaml -- not re-derived.
_STALE_AFTER_SEC = 1.5
_LOST_AFTER_SEC = 5.0
_HEARTBEAT_PERIOD_SEC = 0.5  # publish_rate_hz: 2.0


def _cfg() -> HeartbeatConfig:
    return HeartbeatConfig(stale_after_sec=_STALE_AFTER_SEC, lost_after_sec=_LOST_AFTER_SEC)


def _monitor(self_id: PiId) -> HeartbeatMonitor:
    return HeartbeatMonitor(self_id, config=_cfg())


def _beat_until(monitor: HeartbeatMonitor, peers: list[PiId], start: float, end: float) -> None:
    """Simulate every peer in `peers` publishing a heartbeat every
    _HEARTBEAT_PERIOD_SEC from `start` to `end`."""
    t = start
    while t <= end:
        for p in peers:
            monitor.on_heartbeat(p, now=t)
        t += _HEARTBEAT_PERIOD_SEC


# ── Scenario 1-3: single-Pi loss, observed from every other Pi's own perspective ──


class TestPi2LossPropagation:
    """Pi-2 (human_ai) goes silent -- per failure_policy.yaml's
    pi3_loses_pi2 and (Pi-1 has no explicit pi2-loss policy: Pi-1 only
    tracks Pi-3 for motion authority)."""

    def test_pi3_view_degrades_human_ai_only(self):
        mon = _monitor(PiId.PI3)
        _beat_until(mon, [PiId.PI1, PiId.PI2], start=0.0, end=10.0)
        now = 10.0 + _LOST_AFTER_SEC + 0.1
        # Pi-2 stops beating after t=10; Pi-1 keeps beating.
        mon.on_heartbeat(PiId.PI1, now=now - 0.1)
        states = mon.snapshot(now=now)
        assert states[PiId.PI2] == PiLinkState.LOST
        assert states[PiId.PI1] == PiLinkState.ONLINE

        authority = AuthorityManager(SelfRole.PI3_NAVIGATION_SAFETY)
        snapshot = authority.evaluate(states)
        assert snapshot.motion_authority_available is True
        assert snapshot.human_interaction_permitted is False
        assert snapshot.degraded_modules == ("human_ai",)
        assert snapshot.policy_reason == "pi3_loses_pi2"

    def test_pi3_ignores_pi1_loss_entirely(self):
        """failure_policy.yaml's pi3_loses_pi1: behavior=continue_safe_autonomous,
        safety_state_change=none -- Pi-3 must report nominal even with
        Pi-1 gone, as long as Pi-2 is still reachable."""
        states = {PiId.PI1: PiLinkState.LOST, PiId.PI2: PiLinkState.ONLINE}
        authority = AuthorityManager(SelfRole.PI3_NAVIGATION_SAFETY)
        snapshot = authority.evaluate(states)
        assert snapshot.motion_authority_available is True
        assert snapshot.human_interaction_permitted is True
        assert snapshot.degraded_modules == ()
        assert snapshot.policy_reason == "nominal"


class TestPi3LossPropagation:
    """Pi-3 (navigation_safety, sole motion authority) goes silent --
    per failure_policy.yaml's pi1_loses_pi3 and pi2_loses_pi3, observed
    from BOTH other Pis simultaneously (the real multi-perspective case)."""

    def test_pi1_view_loses_motion_authority(self):
        mon = _monitor(PiId.PI1)
        _beat_until(mon, [PiId.PI2, PiId.PI3], start=0.0, end=10.0)
        now = 10.0 + _LOST_AFTER_SEC + 0.1
        mon.on_heartbeat(PiId.PI2, now=now - 0.1)
        states = mon.snapshot(now=now)

        authority = AuthorityManager(SelfRole.PI1_UI_API)
        snapshot = authority.evaluate(states)
        assert snapshot.motion_authority_available is False
        assert snapshot.degraded_modules == ("navigation_safety",)
        assert snapshot.dashboard_message != "nominal — all Pis reachable"
        assert "unavailable" in snapshot.dashboard_message.lower()

    def test_pi2_view_pauses_proposals_but_keeps_local_perception(self):
        mon = _monitor(PiId.PI2)
        _beat_until(mon, [PiId.PI1, PiId.PI3], start=0.0, end=10.0)
        now = 10.0 + _LOST_AFTER_SEC + 0.1
        mon.on_heartbeat(PiId.PI1, now=now - 0.1)
        states = mon.snapshot(now=now)

        authority = AuthorityManager(SelfRole.PI2_HUMAN_AI)
        snapshot = authority.evaluate(states)
        assert snapshot.should_pause_proposals is True
        assert snapshot.human_interaction_permitted is True  # local ASR/LLM keep running
        assert snapshot.policy_reason == "pi2_loses_pi3"

    def test_both_observers_agree_pi3_is_the_root_cause(self):
        """Pi-1 and Pi-2 independently observing the SAME Pi-3 outage must
        both name pi3 as the cause -- no observer should misattribute it."""
        pi1_mon, pi2_mon = _monitor(PiId.PI1), _monitor(PiId.PI2)
        _beat_until(pi1_mon, [PiId.PI2, PiId.PI3], start=0.0, end=10.0)
        _beat_until(pi2_mon, [PiId.PI1, PiId.PI3], start=0.0, end=10.0)
        now = 10.0 + _LOST_AFTER_SEC + 0.1
        pi1_mon.on_heartbeat(PiId.PI2, now=now - 0.1)
        pi2_mon.on_heartbeat(PiId.PI1, now=now - 0.1)

        pi1_snapshot = AuthorityManager(SelfRole.PI1_UI_API).evaluate(pi1_mon.snapshot(now=now))
        pi2_snapshot = AuthorityManager(SelfRole.PI2_HUMAN_AI).evaluate(pi2_mon.snapshot(now=now))
        assert pi1_snapshot.policy_reason == "pi1_loses_pi3"
        assert pi2_snapshot.policy_reason == "pi2_loses_pi3"


class TestPi1LossPropagation:
    """Pi-1 (ui_api, no safety/actuation authority) goes silent -- must
    have ZERO effect on Pi-3's physical safety per failure_policy.yaml's
    pi3_loses_pi1."""

    def test_pi3_continues_safe_autonomous_unaffected(self):
        mon = _monitor(PiId.PI3)
        _beat_until(mon, [PiId.PI1, PiId.PI2], start=0.0, end=10.0)
        now = 10.0 + _LOST_AFTER_SEC + 0.1
        mon.on_heartbeat(PiId.PI2, now=now - 0.1)
        states = mon.snapshot(now=now)
        assert states[PiId.PI1] == PiLinkState.LOST

        snapshot = AuthorityManager(SelfRole.PI3_NAVIGATION_SAFETY).evaluate(states)
        assert snapshot.motion_authority_available is True
        assert snapshot.degraded_modules == ()
        assert snapshot.policy_reason == "nominal"


# ── Scenario 4: recovery timing ──────────────────────────────────────────────


class TestRecoveryAfterLoss:
    def test_link_returns_online_immediately_on_next_heartbeat(self):
        mon = _monitor(PiId.PI1)
        _beat_until(mon, [PiId.PI2, PiId.PI3], start=0.0, end=10.0)
        # Pi-3 goes silent long enough to be declared LOST...
        lost_at = 10.0 + _LOST_AFTER_SEC + 0.1
        mon.on_heartbeat(PiId.PI2, now=lost_at - 0.1)
        assert mon.state_of(PiId.PI3, now=lost_at) == PiLinkState.LOST

        authority = AuthorityManager(SelfRole.PI1_UI_API)
        assert authority.evaluate(mon.snapshot(now=lost_at)).motion_authority_available is False

        # ...then resumes.
        recovered_at = lost_at + 30.0
        mon.on_heartbeat(PiId.PI3, now=recovered_at)
        mon.on_heartbeat(PiId.PI2, now=recovered_at)
        states = mon.snapshot(now=recovered_at)
        assert states[PiId.PI3] == PiLinkState.ONLINE
        snapshot = authority.evaluate(states)
        assert snapshot.motion_authority_available is True
        assert snapshot.policy_reason == "nominal"

    def test_evaluate_reports_transitions_exactly_once_per_change(self):
        """HeartbeatMonitor.evaluate() (distinct from state_of/snapshot)
        must fire a LinkTransition exactly once per real state change --
        repeated evaluate() calls at unchanged state must not re-fire."""
        mon = _monitor(PiId.PI3)
        transitions_1 = mon.evaluate(now=0.0)  # never seen -> LOST is the initial state, no transition
        assert transitions_1 == []
        mon.on_heartbeat(PiId.PI2, now=1.0)
        transitions_2 = mon.evaluate(now=1.1)
        assert len(transitions_2) == 1
        assert transitions_2[0].new_state == PiLinkState.ONLINE
        transitions_3 = mon.evaluate(now=1.2)  # no new heartbeat, no new transition
        assert transitions_3 == []


# ── Scenario 5: full network partition ───────────────────────────────────────


class TestFullNetworkPartition:
    """All three Pis lose contact simultaneously -- per failure_policy.yaml's
    full_partition_behavior: each Pi applies its own loss policy
    independently, no central arbiter."""

    def test_each_pi_applies_its_own_policy_independently(self):
        # Every Pi's HeartbeatMonitor independently declares both peers LOST.
        empty_states = {PiId.PI1: PiLinkState.LOST, PiId.PI2: PiLinkState.LOST, PiId.PI3: PiLinkState.LOST}

        pi1_snapshot = AuthorityManager(SelfRole.PI1_UI_API).evaluate(empty_states)
        pi2_snapshot = AuthorityManager(SelfRole.PI2_HUMAN_AI).evaluate(empty_states)
        pi3_snapshot = AuthorityManager(SelfRole.PI3_NAVIGATION_SAFETY).evaluate(empty_states)

        # Pi-3 keeps physical safety authority regardless -- the single
        # most important invariant of the whole failure policy.
        assert pi3_snapshot.motion_authority_available is True
        assert pi3_snapshot.human_interaction_permitted is False

        # Pi-1 honestly shows motion authority as unavailable rather than
        # a stale cached value.
        assert pi1_snapshot.motion_authority_available is False

        # Pi-2 pauses proposal emission but keeps local perception alive.
        assert pi2_snapshot.should_pause_proposals is True
        assert pi2_snapshot.human_interaction_permitted is True

    def test_partition_and_pairwise_loss_produce_identical_pi3_behavior(self):
        """Confirms the code's actual design (pi3's evaluate() only checks
        pi2, never pi1): a full partition from pi3's perspective is
        behaviorally identical to losing pi2 alone, since pi1's presence
        never mattered to pi3 in the first place."""
        pairwise = {PiId.PI1: PiLinkState.ONLINE, PiId.PI2: PiLinkState.LOST}
        partition = {PiId.PI1: PiLinkState.LOST, PiId.PI2: PiLinkState.LOST}
        authority = AuthorityManager(SelfRole.PI3_NAVIGATION_SAFETY)
        assert authority.evaluate(pairwise) == authority.evaluate(partition)


# ── Scenario 6: flapping link ─────────────────────────────────────────────────


class TestFlappingLinkDuringPartialConnectivity:
    """A link that repeatedly drops and recovers (e.g. a marginal cable or
    a briefly-overloaded switch) is a materially worse condition than one
    clean loss -- FlapDetector must catch this even while HeartbeatMonitor
    itself just oscillates ONLINE/LOST like any other transition."""

    def test_repeated_short_outages_are_flagged_as_flapping(self):
        mon = _monitor(PiId.PI1)
        flap = FlapDetector([PiId.PI2, PiId.PI3], config=FlapConfig(window_sec=60.0, flap_threshold=3))

        t = 0.0
        for _ in range(4):
            # Pi-3 online for 2s...
            mon.on_heartbeat(PiId.PI3, now=t)
            for trans in mon.evaluate(now=t + 0.1):
                flap.record_transition(trans)
            # ...then silent long enough to be declared LOST.
            t += _LOST_AFTER_SEC + 0.5
            for trans in mon.evaluate(now=t):
                flap.record_transition(trans)
            t += 0.1

        assert flap.is_flapping(PiId.PI3, now=t)
        assert not flap.is_flapping(PiId.PI2, now=t)  # never touched, must not false-positive

    def test_single_clean_loss_is_never_flagged_as_flapping(self):
        mon = _monitor(PiId.PI1)
        flap = FlapDetector([PiId.PI2, PiId.PI3], config=FlapConfig())
        _beat_until(mon, [PiId.PI2, PiId.PI3], start=0.0, end=10.0)
        now = 10.0 + _LOST_AFTER_SEC + 0.1
        mon.on_heartbeat(PiId.PI2, now=now - 0.1)
        for trans in mon.evaluate(now=now):
            flap.record_transition(trans)
        assert not flap.is_flapping(PiId.PI3, now=now)


# ── Scenario 7: simultaneous double loss from one observer ──────────────────


class TestSimultaneousDoubleLoss:
    def test_pi1_losing_both_peers_at_once_still_reports_correctly(self):
        mon = _monitor(PiId.PI1)
        # Neither peer ever beats -- both LOST from the start (honesty
        # rule: never-seen defaults to LOST, not a fabricated ONLINE).
        states = mon.snapshot(now=100.0)
        assert states[PiId.PI2] == PiLinkState.LOST
        assert states[PiId.PI3] == PiLinkState.LOST

        snapshot = AuthorityManager(SelfRole.PI1_UI_API).evaluate(states)
        assert snapshot.motion_authority_available is False
        assert snapshot.policy_reason == "pi1_loses_pi3"

    def test_stale_is_distinguished_from_lost_during_transition_window(self):
        """Between stale_after_sec and lost_after_sec, a link is STALE, not
        yet LOST -- AuthorityManager must not prematurely degrade during
        this grace window (the policy is written in terms of lost_after_sec,
        not stale_after_sec)."""
        mon = _monitor(PiId.PI1)
        mon.on_heartbeat(PiId.PI2, now=0.0)
        mon.on_heartbeat(PiId.PI3, now=0.0)
        mid_window = _STALE_AFTER_SEC + (_LOST_AFTER_SEC - _STALE_AFTER_SEC) / 2
        states = mon.snapshot(now=mid_window)
        assert states[PiId.PI3] == PiLinkState.STALE

        snapshot = AuthorityManager(SelfRole.PI1_UI_API).evaluate(states)
        assert snapshot.motion_authority_available is True  # STALE != LOST
        assert snapshot.policy_reason == "nominal"
