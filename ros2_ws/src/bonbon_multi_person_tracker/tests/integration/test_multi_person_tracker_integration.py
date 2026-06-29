"""End-to-end scenario tests for the multi-person tracking pipeline.

Exercises MultiPersonSceneManager across many realistic cycles — two people
walk in, interact, one leaves and comes back, a third arrives unknown — the
way MultiPersonTrackerNode would drive it once per incoming PersonStateArray,
without requiring rclpy (consistent with this repo's existing integration
test convention, see bonbon_spatial/tests/integration).
"""

from __future__ import annotations

from bonbon_multi_person_tracker.core.lifecycle_state_machine import (
    LifecycleConfig,
    PersonLifecycleState,
)
from bonbon_multi_person_tracker.core.multi_person_scene_manager import MultiPersonSceneManager
from bonbon_multi_person_tracker.core.person_record import RawPersonDetection


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _scene():
    clock = _Clock()
    cfg = LifecycleConfig(confirmation_hits=2, candidate_miss_limit=2, loss_grace_sec=3.0)
    return MultiPersonSceneManager(lifecycle_config=cfg, clock=clock), clock


class TestRealisticTwoPersonScenario:
    def test_two_people_arrive_interact_one_leaves_one_stays(self):
        mgr, clock = _scene()

        # Cycle 1-2: Alice and Bob both walk in.
        for _ in range(2):
            mgr.update(
                [
                    RawPersonDetection("raw_alice", face_id="alice", x=1.0, y=0.0),
                    RawPersonDetection("raw_bob", face_id="bob", x=-1.0, y=0.0),
                ]
            )
            clock.advance(0.1)

        snap = mgr.update(
            [
                RawPersonDetection("raw_alice", face_id="alice", x=1.0, y=0.0),
                RawPersonDetection("raw_bob", face_id="bob", x=-1.0, y=0.0),
            ]
        )
        states = {r.known_person_id: r.lifecycle_state for r in snap}
        assert states["alice"] == PersonLifecycleState.PRESENT
        assert states["bob"] == PersonLifecycleState.PRESENT

        # Alice waves / addresses the robot — gesture package would call this.
        alice_ptid = next(r.person_track_id for r in snap if r.known_person_id == "alice")
        mgr.mark_active_interaction(alice_ptid)
        clock.advance(0.1)
        snap2 = mgr.update(
            [
                RawPersonDetection("raw_alice", face_id="alice", x=1.0, y=0.0),
                RawPersonDetection("raw_bob", face_id="bob", x=-1.0, y=0.0),
            ]
        )
        alice2 = next(r for r in snap2 if r.known_person_id == "alice")
        assert alice2.lifecycle_state == PersonLifecycleState.ACTIVE_INTERACTION
        # Bob's state must be completely unaffected by Alice's interaction —
        # never mix one person's signal into another's record.
        bob2 = next(r for r in snap2 if r.known_person_id == "bob")
        assert bob2.lifecycle_state == PersonLifecycleState.PRESENT

        # Bob walks away (out of frame). Alice remains.
        clock.advance(0.1)
        for _ in range(3):
            mgr.update([RawPersonDetection("raw_alice", face_id="alice", x=1.0, y=0.0)])
            clock.advance(1.0)
        snap3 = mgr.update([RawPersonDetection("raw_alice", face_id="alice", x=1.0, y=0.0)])
        bob3 = next((r for r in snap3 if r.known_person_id == "bob"), None)
        assert bob3 is not None
        assert bob3.lifecycle_state == PersonLifecycleState.LEFT_SCENE
        alice3 = next(r for r in snap3 if r.known_person_id == "alice")
        assert alice3.lifecycle_state in (
            PersonLifecycleState.PRESENT,
            PersonLifecycleState.ACTIVE_INTERACTION,
        )

        # Bob is gone from active tracking, Alice remains.
        assert mgr.active_person_count == 1

    def test_bob_returns_after_leaving_gets_fresh_profile_with_known_identity(self):
        mgr, clock = _scene()
        for _ in range(2):
            mgr.update([RawPersonDetection("raw_bob", face_id="bob", x=0.0, y=0.0)])
            clock.advance(0.1)
        snap = mgr.update([RawPersonDetection("raw_bob", face_id="bob", x=0.0, y=0.0)])
        old_ptid = snap[0].person_track_id

        # Bob leaves for good.
        for _ in range(4):
            mgr.update([])
            clock.advance(1.0)
        assert mgr.active_person_count == 0

        # An hour later (recall_window default 300s in this test) — wait,
        # use a smaller recall window explicitly to keep the test fast.
        clock.advance(5.0)
        snap2 = mgr.update([RawPersonDetection("raw_bob_new", face_id="bob", x=0.0, y=0.0)])
        assert snap2[0].known_person_id == "bob"
        assert snap2[0].person_track_id != old_ptid

    def test_unknown_third_person_arrives_during_existing_interaction(self):
        mgr, clock = _scene()
        for _ in range(2):
            mgr.update([RawPersonDetection("raw_alice", face_id="alice", x=1.0, y=0.0)])
            clock.advance(0.1)
        alice_snap = mgr.update([RawPersonDetection("raw_alice", face_id="alice", x=1.0, y=0.0)])
        alice_ptid = alice_snap[0].person_track_id

        # An unrecognized stranger walks in far away.
        snap = mgr.update(
            [
                RawPersonDetection("raw_alice", face_id="alice", x=1.0, y=0.0),
                RawPersonDetection("raw_stranger", face_id="", x=10.0, y=10.0),
            ]
        )
        stranger = next(r for r in snap if r.person_track_id != alice_ptid)
        assert stranger.known_person_id == ""
        assert stranger.lifecycle_state == PersonLifecycleState.NEW_CANDIDATE
        # Alice's record must be completely unaffected by the stranger's arrival.
        alice = next(r for r in snap if r.person_track_id == alice_ptid)
        assert alice.known_person_id == "alice"


class TestVisionStalenessRobustness:
    def test_empty_detections_ages_everyone_consistently(self):
        """Simulates what MultiPersonTrackerNode does when /bonbon/vision/persons
        goes stale — feeds an empty detection list rather than reusing a frozen
        frame, so presence correctly decays rather than persisting forever."""
        mgr, clock = _scene()
        for _ in range(2):
            mgr.update([RawPersonDetection("raw_x", face_id="x", x=0.0, y=0.0)])
            clock.advance(0.1)
        mgr.update([RawPersonDetection("raw_x", face_id="x", x=0.0, y=0.0)])

        for _ in range(5):
            snap = mgr.update([])  # simulated vision staleness
            clock.advance(1.0)

        final = next((r for r in snap if r.known_person_id == "x"), None)
        # Either currently temporarily_lost (within grace) or already evicted
        # as left_scene — never "present" off a stale/empty feed.
        if final is not None:
            assert final.lifecycle_state in (
                PersonLifecycleState.TEMPORARILY_LOST,
                PersonLifecycleState.LEFT_SCENE,
            )
