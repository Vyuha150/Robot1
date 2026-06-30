"""Integration-style unit tests for MultiPersonSceneManager — the orchestrator.

Covers the explicit rules from the project brief: multi-person, unknown/known
people, arrival, leaving (never from one missed frame), reappearance, and
never mixing two people's identities.
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


def _det(raw_track_id, x=0.0, y=0.0, face_id="", body_embedding_id=""):
    return RawPersonDetection(
        raw_track_id=raw_track_id, face_id=face_id, x=x, y=y, body_embedding_id=body_embedding_id
    )


def _mgr(**cfg_overrides):
    clock = _Clock()
    cfg = LifecycleConfig(**cfg_overrides)
    return MultiPersonSceneManager(lifecycle_config=cfg, clock=clock), clock


def _by_raw(snapshot, raw_track_id):
    return next((r for r in snapshot if r.raw_track_id == raw_track_id), None)


class TestSinglePersonLifecycle:
    def test_new_person_starts_as_new_candidate(self):
        mgr, _ = _mgr(confirmation_hits=2)
        snap = mgr.update([_det("r1")])
        assert len(snap) == 1
        assert snap[0].lifecycle_state == PersonLifecycleState.NEW_CANDIDATE

    def test_confirms_to_present_after_hits(self):
        mgr, _ = _mgr(confirmation_hits=2)
        mgr.update([_det("r1")])
        snap = mgr.update([_det("r1")])
        assert snap[0].lifecycle_state == PersonLifecycleState.PRESENT

    def test_unconfirmed_candidate_discarded_silently_not_published(self):
        """A blip that never confirms must NOT generate a left_scene message —
        nothing meaningful "left" since it never arrived."""
        mgr, _ = _mgr(confirmation_hits=5, candidate_miss_limit=0)
        mgr.update([_det("r1")])  # new_candidate, hit_streak=1
        snap = mgr.update([])  # missed -> discarded immediately (limit=0)
        assert snap == []  # never published as having left


class TestMultiPersonAndIdentityIsolation:
    def test_two_simultaneous_people_get_distinct_ids(self):
        mgr, _ = _mgr(confirmation_hits=1)
        snap = mgr.update([_det("r1", x=0.0), _det("r2", x=5.0)])
        assert len(snap) == 2
        ids = {r.person_track_id for r in snap}
        assert len(ids) == 2

    def test_never_mixes_two_distinct_close_people_via_churn_merge(self):
        """Two DIFFERENT people standing close together, both already active —
        a raw-id churn event on one must never get merged into the other just
        because they're spatially close (spatial evidence is excluded from
        the active-pool churn merge by design)."""
        mgr, _ = _mgr(confirmation_hits=1)
        mgr.update(
            [_det("r1", x=0.0, y=0.0), _det("r2", x=0.3, y=0.0)]
        )  # confirm both, close together
        snap1 = mgr.update([_det("r1", x=0.0, y=0.0), _det("r2", x=0.3, y=0.0)])
        ids_before = {r.raw_track_id: r.person_track_id for r in snap1}

        # r2's raw id churns to r2b (tracker reassigned it) with no face/body
        # evidence — must NOT silently merge into r1's record.
        snap2 = mgr.update([_det("r1", x=0.0, y=0.0), _det("r2b", x=0.3, y=0.0)])
        # r1 keeps its identity; r2b must be a brand-new candidate, not merged
        # into r1's existing person_track_id.
        r1_after = _by_raw(snap2, "r1")
        assert r1_after.person_track_id == ids_before["r1"]
        r2b_after = _by_raw(snap2, "r2b")
        assert r2b_after.person_track_id != ids_before["r1"]
        assert r2b_after.person_track_id != ids_before["r2"]

    def test_churn_merge_succeeds_with_face_id_evidence(self):
        """Tracker-churn (raw id changes) for the SAME person, evidenced by a
        matching face_id, must merge into the existing record rather than
        creating a duplicate."""
        mgr, _ = _mgr(confirmation_hits=1)
        mgr.update([_det("r1", face_id="alice")])
        snap1 = mgr.update([_det("r1", face_id="alice")])
        ptid_before = snap1[0].person_track_id

        snap2 = mgr.update([_det("r1_churned", face_id="alice")])
        assert len(snap2) == 1
        assert snap2[0].person_track_id == ptid_before


class TestArrivalAndLeaving:
    def test_person_leaves_after_grace_window_not_one_frame(self):
        mgr, clock = _mgr(confirmation_hits=1, loss_grace_sec=2.0)
        mgr.update([_det("r1")])  # PRESENT
        snap1 = mgr.update([])  # one missed frame
        assert snap1[0].lifecycle_state == PersonLifecycleState.TEMPORARILY_LOST
        clock.advance(3.0)
        snap2 = mgr.update([])  # grace expired
        left = [r for r in snap2 if r.lifecycle_state == PersonLifecycleState.LEFT_SCENE]
        assert len(left) == 1
        # And they are actually gone from active tracking now.
        assert mgr.active_person_count == 0

    def test_confirmed_person_who_leaves_is_reported_exactly_once(self):
        mgr, clock = _mgr(confirmation_hits=1, loss_grace_sec=1.0)
        mgr.update([_det("r1")])
        mgr.update([])
        clock.advance(2.0)
        snap = mgr.update([])
        assert sum(1 for r in snap if r.lifecycle_state == PersonLifecycleState.LEFT_SCENE) == 1
        snap_next = mgr.update([])
        assert snap_next == []  # not reported again


class TestReappearance:
    def test_person_reappears_via_face_id_after_temporary_loss(self):
        mgr, clock = _mgr(confirmation_hits=1, loss_grace_sec=5.0)
        mgr.update([_det("r1", face_id="bob")])
        snap1 = mgr.update([])  # TEMPORARILY_LOST
        assert snap1[0].lifecycle_state == PersonLifecycleState.TEMPORARILY_LOST
        ptid = snap1[0].person_track_id
        clock.advance(2.0)

        # Different raw track id (camera reacquired them), same face.
        snap2 = mgr.update([_det("r1_new", face_id="bob")])
        assert snap2[0].lifecycle_state == PersonLifecycleState.REAPPEARED
        assert snap2[0].person_track_id == ptid  # SAME person_track_id preserved

        snap3 = mgr.update([_det("r1_new", face_id="bob")])
        assert snap3[0].lifecycle_state == PersonLifecycleState.PRESENT

    def test_reappearance_via_spatial_proximity_without_face(self):
        mgr, clock = _mgr(confirmation_hits=1, loss_grace_sec=5.0)
        mgr.update([_det("r1", x=1.0, y=1.0)])  # no face
        mgr.update([])  # lost
        clock.advance(1.0)
        snap = mgr.update([_det("r1_new", x=1.1, y=1.0)])  # close by, plausible
        assert snap[0].lifecycle_state == PersonLifecycleState.REAPPEARED

    def test_new_person_after_old_left_gets_new_temporary_profile(self):
        """Per brief example #4: new person replaces old -> new temp profile,
        even though departure + arrival may look superficially similar."""
        mgr, clock = _mgr(confirmation_hits=1, loss_grace_sec=1.0)
        mgr.update([_det("r1", face_id="bob")])
        mgr.update([])
        clock.advance(2.0)
        mgr.update([])  # bob officially left_scene now

        snap = mgr.update([_det("r2", face_id="carol")])  # a different, new person
        assert len(snap) == 1
        assert snap[0].known_person_id == "carol"
        # confirmation_hits=1 in this test config -> confirms immediately;
        # the key assertion is that it's a genuinely NEW record, not bob's.
        assert snap[0].lifecycle_state == PersonLifecycleState.PRESENT

    def test_known_person_recalled_after_genuinely_leaving_and_returning(self):
        """Bob leaves for good (left_scene), then returns later — he must get
        a BRAND NEW person_track_id (no resurrection) but known_person_id is
        recovered from the recall buffer."""
        mgr, clock = _mgr(confirmation_hits=1, loss_grace_sec=1.0)
        mgr.update([_det("r1", face_id="bob")])
        snap_present = mgr.update([_det("r1", face_id="bob")])
        old_ptid = snap_present[0].person_track_id
        mgr.update([])
        clock.advance(2.0)
        mgr.update([])  # left_scene + evicted + remembered

        clock.advance(10.0)
        snap_return = mgr.update([_det("r9", face_id="bob")])
        assert snap_return[0].known_person_id == "bob"
        assert snap_return[0].person_track_id != old_ptid  # new profile, not resurrected


class TestActiveInteractionHook:
    def test_mark_active_interaction_changes_state(self):
        mgr, _ = _mgr(confirmation_hits=1)
        snap = mgr.update([_det("r1")])
        ptid = snap[0].person_track_id
        assert mgr.mark_active_interaction(ptid) is True
        snap2 = mgr.update([_det("r1")])
        assert snap2[0].lifecycle_state == PersonLifecycleState.ACTIVE_INTERACTION

    def test_mark_active_interaction_unknown_id_returns_false(self):
        mgr, _ = _mgr()
        assert mgr.mark_active_interaction("does_not_exist") is False


class TestBoundedScene:
    def test_max_persons_is_enforced(self):
        mgr, _ = _mgr(confirmation_hits=1)
        mgr._max_persons = 3
        dets = [_det(f"r{i}", x=float(i) * 10) for i in range(10)]
        snap = mgr.update(dets)
        assert len(snap) <= 3
        assert mgr.active_person_count <= 3


class TestIdSwitchMetric:
    """Compliance audit, check #9: a person-tracking ID-switch metric must
    exist. Pass 3 (churn merge against ACTIVE people, not TEMPORARILY_LOST)
    is exactly the MOT-literature definition of an ID switch: someone who
    was continuously present got a NEW raw_track_id from the upstream
    tracker, and the system caught it via re-identification rather than
    spawning a duplicate person."""

    def test_starts_at_zero(self):
        mgr, _ = _mgr(confirmation_hits=1)
        assert mgr.id_switch_count == 0

    def test_raw_id_churn_on_an_active_person_increments_the_counter(self):
        mgr, _ = _mgr(confirmation_hits=1)
        snap = mgr.update([_det("r1", face_id="bob")])
        ptid = snap[0].person_track_id
        assert mgr.id_switch_count == 0

        # Upstream tracker assigns a new raw ID to the same, continuously
        # present person -- not a real disappearance/reappearance.
        snap2 = mgr.update([_det("r2", face_id="bob")])
        assert mgr.id_switch_count == 1
        assert snap2[0].person_track_id == ptid  # identity preserved

    def test_reappearance_after_real_loss_does_not_count_as_id_switch(self):
        """Pass 2 (reappearance against TEMPORARILY_LOST) is a different
        metric -- track re-acquisition after a genuine gap -- and must NOT
        inflate the ID-switch count."""
        mgr, clock = _mgr(confirmation_hits=1, loss_grace_sec=5.0)
        mgr.update([_det("r1", face_id="bob")])
        mgr.update([])  # missed -> TEMPORARILY_LOST
        clock.advance(2.0)
        snap = mgr.update([_det("r1_new", face_id="bob")])  # reappears
        assert snap[0].lifecycle_state == PersonLifecycleState.REAPPEARED
        assert mgr.id_switch_count == 0

    def test_genuinely_new_person_does_not_count_as_id_switch(self):
        mgr, _ = _mgr(confirmation_hits=1)
        mgr.update([_det("r1", face_id="bob")])
        mgr.update([_det("r2", face_id="carol", x=10.0)])
        assert mgr.id_switch_count == 0

    def test_counter_is_cumulative_across_cycles(self):
        mgr, _ = _mgr(confirmation_hits=1)
        mgr.update([_det("r1", face_id="bob")])
        mgr.update([_det("r2", face_id="bob")])  # switch 1
        mgr.update([_det("r3", face_id="bob")])  # switch 2
        assert mgr.id_switch_count == 2
