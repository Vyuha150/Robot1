"""Tests for associate_doa_to_person — audio-visual speaker association."""

from __future__ import annotations

from bonbon_speaker_intelligence.core.audio_visual_associator import (
    TrackedPersonBearing,
    associate_doa_to_person,
)


class TestBasicMatching:
    def test_matches_nearest_bearing(self):
        people = [
            TrackedPersonBearing("p_left", 45.0),
            TrackedPersonBearing("p_right", -45.0),
        ]
        result = associate_doa_to_person(40.0, people)
        assert result.matched
        assert result.person_track_id == "p_left"

    def test_no_tracked_persons_unmatched(self):
        result = associate_doa_to_person(30.0, [])
        assert result.matched is False

    def test_unknown_doa_sentinel_unmatched(self):
        people = [TrackedPersonBearing("p1", 30.0)]
        result = associate_doa_to_person(-1.0, people)
        assert result.matched is False


class TestTolerance:
    def test_out_of_tolerance_rejected(self):
        people = [TrackedPersonBearing("p1", 0.0)]
        result = associate_doa_to_person(90.0, people, max_bearing_delta_deg=20.0)
        assert result.matched is False

    def test_within_tolerance_accepted_with_scaled_confidence(self):
        people = [TrackedPersonBearing("p1", 0.0)]
        close = associate_doa_to_person(2.0, people, max_bearing_delta_deg=20.0)
        far = associate_doa_to_person(18.0, people, max_bearing_delta_deg=20.0)
        assert close.matched and far.matched
        assert close.confidence > far.confidence


class TestAngleWraparound:
    def test_wraparound_near_180_still_matches(self):
        people = [TrackedPersonBearing("p1", 178.0)]
        result = associate_doa_to_person(-179.0, people, max_bearing_delta_deg=10.0)
        assert result.matched
        assert result.person_track_id == "p1"


class TestMultiplePeopleDistinct:
    def test_does_not_cross_match_when_clearly_separated(self):
        people = [
            TrackedPersonBearing("near", 10.0),
            TrackedPersonBearing("far", 170.0),
        ]
        result = associate_doa_to_person(8.0, people, max_bearing_delta_deg=30.0)
        assert result.person_track_id == "near"
