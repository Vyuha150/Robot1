"""Tests for build_evidence_summary."""

from __future__ import annotations

from bonbon_human_state_fusion.core.evidence_summary import EvidenceInputs, build_evidence_summary


def _ev(**overrides):
    base = dict(
        known_person_id="",
        lifecycle_state="present",
        emotional_state="neutral",
        emotional_state_source="",
        current_gesture="none",
        gesture_age_sec=None,
        active_speaker_status="silent",
        has_transcript=False,
    )
    base.update(overrides)
    return EvidenceInputs(**base)


class TestIdentity:
    def test_known_person_named(self):
        s = build_evidence_summary(_ev(known_person_id="bob"))
        assert "known (bob)" in s

    def test_unknown_person_labeled_unidentified(self):
        s = build_evidence_summary(_ev(known_person_id=""))
        assert "unidentified" in s


class TestEmotion:
    def test_available_emotion_includes_source(self):
        s = build_evidence_summary(
            _ev(emotional_state="happy", emotional_state_source="bonbon_affective_ai")
        )
        assert "happy" in s
        assert "bonbon_affective_ai" in s

    def test_unavailable_emotion_flagged(self):
        s = build_evidence_summary(_ev(emotional_state_source=""))
        assert "emotion: unavailable" in s


class TestGesture:
    def test_no_gesture_reported_as_none(self):
        s = build_evidence_summary(_ev(current_gesture="none"))
        assert "gesture: none" in s

    def test_active_gesture_includes_age(self):
        s = build_evidence_summary(_ev(current_gesture="wave", gesture_age_sec=1.5))
        assert "wave" in s
        assert "1.5s ago" in s

    def test_unknown_gesture_treated_as_none(self):
        s = build_evidence_summary(_ev(current_gesture="unknown_gesture"))
        assert "gesture: none" in s


class TestSpeech:
    def test_speaking_with_transcript(self):
        s = build_evidence_summary(_ev(active_speaker_status="speaking", has_transcript=True))
        assert "speaking" in s
        assert "transcript available" in s

    def test_silent_without_transcript(self):
        s = build_evidence_summary(_ev(active_speaker_status="silent", has_transcript=False))
        assert "silent" in s
        assert "transcript available" not in s


class TestOverallStructure:
    def test_all_sections_present_and_pipe_delimited(self):
        s = build_evidence_summary(_ev())
        sections = s.split(" | ")
        assert len(sections) == 5
        assert sections[0].startswith("identity:")
        assert sections[1].startswith("lifecycle:")
        assert sections[2].startswith("emotion:")
        assert sections[3].startswith("gesture:")
        assert sections[4].startswith("speech:")
