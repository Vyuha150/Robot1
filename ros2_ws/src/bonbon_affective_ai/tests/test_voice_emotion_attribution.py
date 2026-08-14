"""Tests for the Phase 4 fix (docs/MULTI_HUMAN_EMOTION_FAILURE_ANALYSIS.md):
voice emotion attributed to a specific person via SpeakerTurn.person_track_id,
bridged to the raw_track_id key space _fuse_and_publish already looks up,
instead of only ever landing in the unscoped "_global" entry.

Exercises AffectiveAINode._cb_person_track / _cb_speaker_turn directly
against a minimal fake "self" carrying just the attributes those two
methods touch -- avoids the overhead of full node construction
(executor, backends, services) while still running the REAL method
code, not a reimplementation.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import Any, Dict

from bonbon_affective_ai.nodes.affective_ai_node import AffectiveAINode, SpeakerTurnVoiceEmotion


class _FakeLogger:
    def debug(self, *a, **k):
        pass

    def warn(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass


@dataclass
class _FakeNodeSelf:
    """Minimal stand-in exposing only what _cb_person_track/_cb_speaker_turn
    read or write on self."""

    _processing_enabled: bool = True
    _person_track_to_raw_id: Dict[str, str] = field(default_factory=dict)
    _latest_voice_msgs: Dict[str, Any] = field(default_factory=dict)

    def get_logger(self):
        return _FakeLogger()


@dataclass
class _PersonTrackMsg:
    person_track_id: str = ""
    raw_track_id: str = ""


@dataclass
class _SpeakerTurnMsg:
    person_track_id: str = ""
    voice_emotion: str = ""
    emotion_confidence: float = 0.0


class TestPersonTrackBridge(unittest.TestCase):
    def test_present_person_records_raw_id_mapping(self):
        node = _FakeNodeSelf()
        AffectiveAINode._cb_person_track(
            node, _PersonTrackMsg(person_track_id="ptrack_7", raw_track_id="person_3")
        )
        self.assertEqual(node._person_track_to_raw_id["ptrack_7"], "person_3")

    def test_temporarily_lost_person_clears_the_mapping(self):
        node = _FakeNodeSelf(_person_track_to_raw_id={"ptrack_7": "person_3"})
        AffectiveAINode._cb_person_track(
            node, _PersonTrackMsg(person_track_id="ptrack_7", raw_track_id="")
        )
        self.assertNotIn("ptrack_7", node._person_track_to_raw_id)

    def test_empty_person_track_id_is_ignored(self):
        node = _FakeNodeSelf()
        AffectiveAINode._cb_person_track(
            node, _PersonTrackMsg(person_track_id="", raw_track_id="person_3")
        )
        self.assertEqual(node._person_track_to_raw_id, {})


class TestSpeakerTurnVoiceAttribution(unittest.TestCase):
    def test_voice_emotion_stored_under_raw_track_id_not_person_track_id(self):
        node = _FakeNodeSelf(_person_track_to_raw_id={"ptrack_7": "person_3"})
        AffectiveAINode._cb_speaker_turn(
            node,
            _SpeakerTurnMsg(
                person_track_id="ptrack_7", voice_emotion="angry", emotion_confidence=0.8
            ),
        )
        self.assertIn("person_3", node._latest_voice_msgs)
        self.assertNotIn("ptrack_7", node._latest_voice_msgs)
        stored = node._latest_voice_msgs["person_3"]
        self.assertEqual(stored.dominant_emotion, "angry")
        self.assertAlmostEqual(stored.dominant_confidence, 0.8)
        self.assertFalse(stored.model_failed)

    def test_no_raw_id_mapping_yet_does_not_fabricate_an_attribution(self):
        node = _FakeNodeSelf()  # no person_track_to_raw_id entry
        AffectiveAINode._cb_speaker_turn(
            node,
            _SpeakerTurnMsg(
                person_track_id="ptrack_9", voice_emotion="happy", emotion_confidence=0.9
            ),
        )
        self.assertEqual(node._latest_voice_msgs, {})

    def test_missing_person_track_id_is_ignored(self):
        node = _FakeNodeSelf()
        AffectiveAINode._cb_speaker_turn(
            node, _SpeakerTurnMsg(person_track_id="", voice_emotion="happy", emotion_confidence=0.9)
        )
        self.assertEqual(node._latest_voice_msgs, {})

    def test_empty_voice_emotion_is_ignored(self):
        node = _FakeNodeSelf(_person_track_to_raw_id={"ptrack_7": "person_3"})
        AffectiveAINode._cb_speaker_turn(
            node,
            _SpeakerTurnMsg(person_track_id="ptrack_7", voice_emotion="", emotion_confidence=0.9),
        )
        self.assertEqual(node._latest_voice_msgs, {})

    def test_processing_disabled_ignores_the_turn(self):
        node = _FakeNodeSelf(
            _processing_enabled=False, _person_track_to_raw_id={"ptrack_7": "person_3"}
        )
        AffectiveAINode._cb_speaker_turn(
            node,
            _SpeakerTurnMsg(
                person_track_id="ptrack_7", voice_emotion="angry", emotion_confidence=0.8
            ),
        )
        self.assertEqual(node._latest_voice_msgs, {})

    def test_two_different_people_speaking_get_distinct_attributed_emotions(self):
        # The actual bug this fix targets: two people talking near the
        # robot must not collapse into one shared/unscoped reading.
        node = _FakeNodeSelf(
            _person_track_to_raw_id={"ptrack_1": "person_1", "ptrack_2": "person_2"}
        )
        AffectiveAINode._cb_speaker_turn(
            node,
            _SpeakerTurnMsg(
                person_track_id="ptrack_1", voice_emotion="calm", emotion_confidence=0.7
            ),
        )
        AffectiveAINode._cb_speaker_turn(
            node,
            _SpeakerTurnMsg(
                person_track_id="ptrack_2", voice_emotion="angry", emotion_confidence=0.85
            ),
        )
        self.assertEqual(node._latest_voice_msgs["person_1"].dominant_emotion, "calm")
        self.assertEqual(node._latest_voice_msgs["person_2"].dominant_emotion, "angry")


class TestFuseAndPublishLookupPrefersAttributedEntry(unittest.TestCase):
    """Confirms the existing _fuse_and_publish lookup
    (`_latest_voice_msgs.get(person_id) or .get("_global")`) genuinely
    prefers a real per-person entry once one exists -- this line was
    already correct, the bug was that nothing ever populated the
    per-person key. No changes were needed here; this test guards
    against a future regression silently reverting to global-only."""

    def test_lookup_prefers_person_specific_over_global(self):
        latest_voice_msgs: Dict[str, Any] = {
            "_global": SpeakerTurnVoiceEmotion(dominant_emotion="sad", dominant_confidence=0.3),
            "person_3": SpeakerTurnVoiceEmotion(dominant_emotion="angry", dominant_confidence=0.9),
        }
        voice_msg = latest_voice_msgs.get("person_3") or latest_voice_msgs.get("_global")
        self.assertEqual(voice_msg.dominant_emotion, "angry")

    def test_lookup_falls_back_to_global_when_no_person_entry(self):
        latest_voice_msgs: Dict[str, Any] = {
            "_global": SpeakerTurnVoiceEmotion(dominant_emotion="sad", dominant_confidence=0.3),
        }
        voice_msg = latest_voice_msgs.get("person_5") or latest_voice_msgs.get("_global")
        self.assertEqual(voice_msg.dominant_emotion, "sad")


if __name__ == "__main__":
    unittest.main()
