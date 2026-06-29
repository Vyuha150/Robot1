"""Unit tests for the face_id / spatial-proximity / body-reid associators."""

from __future__ import annotations

from dataclasses import dataclass

from bonbon_multi_person_tracker.core.identity_associator import (
    AssociationCandidate,
    BodyReIDAssociator,
    FaceIdAssociator,
    IdentityAssociator,
    SpatialProximityAssociator,
)


@dataclass
class _FakeTracked:
    person_track_id: str
    known_face_id: str = ""
    last_x: float = 0.0
    last_y: float = 0.0
    last_z: float = 0.0
    time_since_last_seen_sec: float = 1.0
    body_embedding_id: str = ""


class TestFaceIdAssociator:
    def test_matches_on_exact_face_id(self):
        a = FaceIdAssociator()
        pool = [_FakeTracked("p1", known_face_id="bob"), _FakeTracked("p2", known_face_id="alice")]
        cand = AssociationCandidate("raw_5", face_id="alice", x=0, y=0, z=0)
        r = a.try_associate(cand, pool)
        assert r.matched and r.person_track_id == "p2"
        assert r.confidence >= 0.9

    def test_no_match_when_face_id_empty(self):
        a = FaceIdAssociator()
        pool = [_FakeTracked("p1", known_face_id="bob")]
        cand = AssociationCandidate("raw_5", face_id="", x=0, y=0, z=0)
        assert a.try_associate(cand, pool).matched is False

    def test_no_match_when_no_pool_entry_has_that_face(self):
        a = FaceIdAssociator()
        pool = [_FakeTracked("p1", known_face_id="bob")]
        cand = AssociationCandidate("raw_5", face_id="charlie", x=0, y=0, z=0)
        assert a.try_associate(cand, pool).matched is False


class TestSpatialProximityAssociator:
    def test_matches_within_plausible_speed_gate(self):
        a = SpatialProximityAssociator(max_speed_mps=1.0, slack_radius_m=0.2)
        pool = [_FakeTracked("p1", last_x=0.0, last_y=0.0, time_since_last_seen_sec=1.0)]
        cand = AssociationCandidate(
            "raw_2", face_id="", x=0.5, y=0.0, z=0.0
        )  # 0.5m in 1s, gate=1.2m
        r = a.try_associate(cand, pool)
        assert r.matched and r.person_track_id == "p1"

    def test_rejects_implausible_teleport(self):
        a = SpatialProximityAssociator(max_speed_mps=1.0, slack_radius_m=0.2)
        pool = [_FakeTracked("p1", last_x=0.0, last_y=0.0, time_since_last_seen_sec=0.5)]
        cand = AssociationCandidate(
            "raw_2", face_id="", x=10.0, y=0.0, z=0.0
        )  # 10m in 0.5s — impossible
        r = a.try_associate(cand, pool)
        assert r.matched is False

    def test_picks_nearest_when_multiple_in_gate(self):
        a = SpatialProximityAssociator(max_speed_mps=2.0, slack_radius_m=1.0)
        pool = [
            _FakeTracked("far", last_x=1.0, last_y=0.0, time_since_last_seen_sec=1.0),
            _FakeTracked("near", last_x=0.1, last_y=0.0, time_since_last_seen_sec=1.0),
        ]
        cand = AssociationCandidate("raw_2", face_id="", x=0.0, y=0.0, z=0.0)
        r = a.try_associate(cand, pool)
        assert r.person_track_id == "near"

    def test_empty_pool_no_match(self):
        a = SpatialProximityAssociator()
        cand = AssociationCandidate("raw_2", face_id="", x=0, y=0, z=0)
        assert a.try_associate(cand, []).matched is False


class TestBodyReIDAssociator:
    def test_matches_on_embedding_id(self):
        a = BodyReIDAssociator()
        pool = [_FakeTracked("p1", body_embedding_id="emb_42")]
        cand = AssociationCandidate("raw_3", face_id="", x=0, y=0, z=0, body_embedding_id="emb_42")
        r = a.try_associate(cand, pool)
        assert r.matched and r.person_track_id == "p1"

    def test_no_match_without_embedding(self):
        a = BodyReIDAssociator()
        pool = [_FakeTracked("p1", body_embedding_id="emb_42")]
        cand = AssociationCandidate("raw_3", face_id="", x=0, y=0, z=0, body_embedding_id="")
        assert a.try_associate(cand, pool).matched is False


class TestIdentityAssociatorPriority:
    def test_face_id_wins_over_spatial_proximity(self):
        """Even if spatial proximity would match a DIFFERENT person, a real
        face_id match must take priority — never mix identities on weak
        spatial evidence when strong evidence disagrees."""
        ia = IdentityAssociator()
        pool = [
            _FakeTracked(
                "near_but_wrong_face",
                known_face_id="bob",
                last_x=0.0,
                last_y=0.0,
                time_since_last_seen_sec=1.0,
            ),
            _FakeTracked(
                "far_but_correct_face",
                known_face_id="alice",
                last_x=5.0,
                last_y=5.0,
                time_since_last_seen_sec=1.0,
            ),
        ]
        cand = AssociationCandidate("raw_9", face_id="alice", x=0.1, y=0.1, z=0.0)
        r = ia.associate(cand, pool)
        assert r.matched and r.person_track_id == "far_but_correct_face"
        assert r.strategy == "face_id"

    def test_falls_back_to_spatial_when_no_face_or_body_match(self):
        ia = IdentityAssociator()
        pool = [_FakeTracked("p1", last_x=0.0, last_y=0.0, time_since_last_seen_sec=1.0)]
        cand = AssociationCandidate("raw_1", face_id="", x=0.1, y=0.1, z=0.0)
        r = ia.associate(cand, pool)
        assert r.matched and r.strategy == "spatial_proximity"

    def test_no_strategy_matches_returns_unmatched(self):
        ia = IdentityAssociator()
        pool = [
            _FakeTracked(
                "p1", known_face_id="bob", last_x=0.0, last_y=0.0, time_since_last_seen_sec=1.0
            )
        ]
        cand = AssociationCandidate("raw_1", face_id="someone_else", x=99.0, y=99.0, z=0.0)
        r = ia.associate(cand, pool)
        assert r.matched is False

    def test_empty_pool_always_unmatched(self):
        ia = IdentityAssociator()
        cand = AssociationCandidate("raw_1", face_id="bob", x=0, y=0, z=0)
        assert ia.associate(cand, []).matched is False
