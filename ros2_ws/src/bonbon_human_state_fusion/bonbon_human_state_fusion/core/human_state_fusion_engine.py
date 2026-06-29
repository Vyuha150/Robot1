"""HumanStateFusionEngine — the per-person fusion orchestrator.

Fuses (without re-deriving any of them):
    bonbon_multi_person_tracker  -> PersonTrack        (identity, lifecycle, location)
    bonbon_affective_ai          -> HumanEmotionState  (already-fused emotion)
                                  -> FaceEmotion, VoiceEmotion (raw per-modality)
    bonbon_gesture                -> GestureEvent        (current gesture)
    bonbon_speaker_intelligence  -> SpeakerTurn         (who's speaking, transcript)
    bonbon_perception_ai         -> UserIntent          (text intent)
    bonbon_affective_ai          -> TextEmotion         (text sentiment)

Cross-ID-space bridging (the actual hard part of this package):
    - GestureEvent.person_track_id and SpeakerTurn.person_track_id are
      ALREADY in person_track_id space (bonbon_gesture/bonbon_speaker_intelligence
      were built after bonbon_multi_person_tracker existed) — direct joins.
    - HumanEmotionState/FaceEmotion/VoiceEmotion predate bonbon_multi_person_tracker
      and key off bonbon_vision's raw per-frame track_id ("person_3" / int 3).
      Bridged via PersonTrack.raw_track_id, refreshed every cycle (and
      correctly empty while temporarily_lost, since the raw ID is untrustworthy
      once the underlying detection is gone — see PersonTrack.msg).
    - UserIntent/TextEmotion key off the diarizer's per-utterance speaker_id,
      yet another ID space with no direct bridge. Attributed to whichever
      person_track_id was the most recent active speaker (text always follows
      speech) within a short window — never guessed across an implausible gap.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from bonbon_human_state_fusion.core.active_speaker_tracker import ActiveSpeakerTracker
from bonbon_human_state_fusion.core.confidence_calculator import (
    ConfidenceInputs,
    compute_confidence,
)
from bonbon_human_state_fusion.core.evidence_summary import EvidenceInputs, build_evidence_summary
from bonbon_human_state_fusion.core.urgency_engagement_estimator import (
    estimate_engagement,
    estimate_urgency,
)

_GESTURE_RECENCY_SEC = 3.0
_EMOTION_RECENCY_SEC = 6.0
_TEXT_BRIDGE_MAX_AGE_SEC = 3.0


def classify_proximity_zone(distance_m: float) -> str:
    """Simple, documented proxemics buckets for social interaction purposes
    (distinct from bonbon_spatial's collision-avoidance proxemic zones, which
    serve navigation/stop-distance decisions, not interaction style)."""
    if distance_m < 1.2:
        return "personal_space"
    if distance_m < 3.6:
        return "social_space"
    return "public_space"


@dataclass
class HumanStateResult:
    person_track_id: str
    known_person_id: str
    lifecycle_state: str
    active_speaker_status: str
    last_transcript: str
    transcript_confidence: float
    current_gesture: str
    gesture_confidence: float
    face_expression: str
    voice_emotion: str
    text_intent: str
    text_sentiment: str
    emotional_state: str
    location_x: float
    location_y: float
    location_z: float
    proximity_zone: str
    engagement_level: float
    urgency_level: float
    confidence: float
    recommended_robot_response_style: str
    recommended_robot_distance_m: float
    requires_operator_alert: bool
    evidence_summary: str


@dataclass
class _PersonFusionRecord:
    person_track_id: str
    known_person_id: str = ""
    lifecycle_state: str = "new_candidate"
    raw_track_id: str = ""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    lifecycle_confidence: float = 0.5

    face_expression: str = ""
    voice_emotion: str = ""
    face_voice_updated_at: float = -1e9

    emotional_state: str = ""
    emotion_confidence: float | None = None
    emotion_response_style: str = ""
    emotion_distance_m: float | None = None
    emotion_requires_alert: bool = False
    emotion_updated_at: float = -1e9

    current_gesture: str = "none"
    gesture_confidence: float = 0.0
    gesture_requires_immediate: bool = False
    gesture_updated_at: float = -1e9

    text_intent: str = ""
    text_sentiment: str = ""
    text_emergency_detected: bool = False


class HumanStateFusionEngine:
    def __init__(
        self,
        speaking_window_sec: float = 2.0,
        recently_spoke_window_sec: float = 15.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._clock = clock or time.monotonic
        self._records: dict[str, _PersonFusionRecord] = {}
        self._raw_track_to_person: dict[str, str] = {}
        self._speaker_tracker = ActiveSpeakerTracker(
            speaking_window_sec=speaking_window_sec,
            recently_spoke_window_sec=recently_spoke_window_sec,
            clock=self._clock,
        )

    # ── Ingest: bonbon_multi_person_tracker (authoritative identity) ───────

    def update_person_track(
        self,
        person_track_id: str,
        known_person_id: str,
        lifecycle_state: str,
        raw_track_id: str,
        x: float,
        y: float,
        z: float,
        confidence: float,
    ) -> None:
        rec = self._records.setdefault(person_track_id, _PersonFusionRecord(person_track_id))
        rec.known_person_id = known_person_id
        rec.lifecycle_state = lifecycle_state
        rec.x, rec.y, rec.z = x, y, z
        rec.lifecycle_confidence = confidence

        if rec.raw_track_id and rec.raw_track_id in self._raw_track_to_person:
            del self._raw_track_to_person[rec.raw_track_id]
        rec.raw_track_id = raw_track_id
        if raw_track_id:
            self._raw_track_to_person[raw_track_id] = person_track_id

    def evict_left_scene(self) -> list[str]:
        """Removes records that reached left_scene (call after building/
        publishing this cycle's HumanState, mirroring bonbon_multi_person_tracker's
        snapshot-then-evict pattern). Returns the evicted person_track_ids."""
        evicted = [pid for pid, r in self._records.items() if r.lifecycle_state == "left_scene"]
        for pid in evicted:
            rec = self._records.pop(pid)
            if rec.raw_track_id:
                self._raw_track_to_person.pop(rec.raw_track_id, None)
            self._speaker_tracker.forget(pid)
        return evicted

    # ── Ingest: bonbon_affective_ai (already-fused + raw per-modality) ──────

    def update_human_emotion_state(
        self,
        raw_person_id: str,
        dominant_state: str,
        dominant_confidence: float,
        recommended_response_style: str,
        recommended_distance_m: float,
        requires_operator_alert: bool,
    ) -> bool:
        """Returns True if successfully bridged to a known person_track_id."""
        person_track_id = self._raw_track_to_person.get(raw_person_id, "")
        if not person_track_id:
            return False
        rec = self._records.get(person_track_id)
        if rec is None:
            return False
        rec.emotional_state = dominant_state
        rec.emotion_confidence = dominant_confidence
        rec.emotion_response_style = recommended_response_style
        rec.emotion_distance_m = recommended_distance_m
        rec.emotion_requires_alert = requires_operator_alert
        rec.emotion_updated_at = self._clock()
        return True

    def update_face_emotion(self, raw_person_id: str, dominant_emotion: str) -> bool:
        person_track_id = self._raw_track_to_person.get(raw_person_id, "")
        rec = self._records.get(person_track_id) if person_track_id else None
        if rec is None:
            return False
        rec.face_expression = dominant_emotion
        rec.face_voice_updated_at = self._clock()
        return True

    def update_voice_emotion(self, raw_person_id: str, dominant_emotion: str) -> bool:
        if not raw_person_id:
            return False  # bonbon_affective_ai's voice analyzer is often unattributed
        person_track_id = self._raw_track_to_person.get(raw_person_id, "")
        rec = self._records.get(person_track_id) if person_track_id else None
        if rec is None:
            return False
        rec.voice_emotion = dominant_emotion
        rec.face_voice_updated_at = self._clock()
        return True

    # ── Ingest: bonbon_gesture (direct person_track_id join) ────────────────

    def update_gesture_event(
        self, person_track_id: str, gesture_type: str, confidence: float, requires_immediate: bool
    ) -> bool:
        rec = self._records.get(person_track_id) if person_track_id else None
        if rec is None:
            return False
        rec.current_gesture = gesture_type
        rec.gesture_confidence = confidence
        rec.gesture_requires_immediate = requires_immediate
        rec.gesture_updated_at = self._clock()
        return True

    # ── Ingest: bonbon_speaker_intelligence (direct person_track_id join) ──

    def update_speaker_turn(
        self, person_track_id: str, transcript: str, transcript_confidence: float
    ) -> bool:
        if not person_track_id:
            return False
        if person_track_id not in self._records:
            return False
        self._speaker_tracker.record_turn(person_track_id, transcript, transcript_confidence)
        return True

    # ── Ingest: text intent/sentiment (bridged via most-recent-speaker) ────

    def update_user_intent(self, intent_class: str) -> bool:
        target = self._speaker_tracker.most_recent_speaker(_TEXT_BRIDGE_MAX_AGE_SEC)
        rec = self._records.get(target) if target else None
        if rec is None:
            return False
        rec.text_intent = intent_class
        return True

    def update_text_emotion(self, dominant_emotion: str, emergency_detected: bool = False) -> bool:
        target = self._speaker_tracker.most_recent_speaker(_TEXT_BRIDGE_MAX_AGE_SEC)
        rec = self._records.get(target) if target else None
        if rec is None:
            return False
        rec.text_sentiment = dominant_emotion
        rec.text_emergency_detected = emergency_detected
        return True

    # ── Build ────────────────────────────────────────────────────────────────

    def build_human_state(self, person_track_id: str) -> HumanStateResult | None:
        rec = self._records.get(person_track_id)
        if rec is None:
            return None

        now = self._clock()
        speaker_status = self._speaker_tracker.status_for(person_track_id)
        transcript, transcript_conf = self._speaker_tracker.last_transcript_for(person_track_id)

        gesture_fresh = (now - rec.gesture_updated_at) <= _GESTURE_RECENCY_SEC
        emotion_fresh = (now - rec.emotion_updated_at) <= _EMOTION_RECENCY_SEC
        has_transcript = bool(transcript)

        engagement = estimate_engagement(
            rec.lifecycle_state,
            speaker_status,
            gesture_fresh and rec.current_gesture not in ("none", "unknown_gesture"),
        )
        urgency = estimate_urgency(
            rec.emotional_state if emotion_fresh else "",
            gesture_fresh and rec.gesture_requires_immediate,
            rec.text_emergency_detected,
        )
        confidence = compute_confidence(
            ConfidenceInputs(
                lifecycle_confidence=rec.lifecycle_confidence,
                emotion_confidence=rec.emotion_confidence if emotion_fresh else None,
                gesture_confidence=rec.gesture_confidence if gesture_fresh else None,
                speech_confidence=transcript_conf if has_transcript else None,
            )
        )

        distance_m = (rec.x**2 + rec.y**2) ** 0.5
        proximity = classify_proximity_zone(distance_m)

        response_style = (
            rec.emotion_response_style if emotion_fresh and rec.emotion_response_style else "normal"
        )
        recommended_distance = (
            rec.emotion_distance_m
            if emotion_fresh and rec.emotion_distance_m is not None
            else (1.2 if proximity == "personal_space" else 1.0)
        )
        requires_alert = (emotion_fresh and rec.emotion_requires_alert) or (
            gesture_fresh and rec.gesture_requires_immediate
        )

        evidence = build_evidence_summary(
            EvidenceInputs(
                known_person_id=rec.known_person_id,
                lifecycle_state=rec.lifecycle_state,
                emotional_state=rec.emotional_state if emotion_fresh else "",
                emotional_state_source=(
                    "bonbon_affective_ai" if emotion_fresh and rec.emotional_state else ""
                ),
                current_gesture=rec.current_gesture if gesture_fresh else "none",
                gesture_age_sec=(now - rec.gesture_updated_at) if gesture_fresh else None,
                active_speaker_status=speaker_status,
                has_transcript=has_transcript,
            )
        )

        return HumanStateResult(
            person_track_id=person_track_id,
            known_person_id=rec.known_person_id,
            lifecycle_state=rec.lifecycle_state,
            active_speaker_status=speaker_status,
            last_transcript=transcript,
            transcript_confidence=transcript_conf,
            current_gesture=rec.current_gesture if gesture_fresh else "none",
            gesture_confidence=rec.gesture_confidence if gesture_fresh else 0.0,
            face_expression=rec.face_expression,
            voice_emotion=rec.voice_emotion,
            text_intent=rec.text_intent,
            text_sentiment=rec.text_sentiment,
            emotional_state=rec.emotional_state if emotion_fresh else "",
            location_x=rec.x,
            location_y=rec.y,
            location_z=rec.z,
            proximity_zone=proximity,
            engagement_level=engagement,
            urgency_level=urgency,
            confidence=confidence,
            recommended_robot_response_style=response_style,
            recommended_robot_distance_m=recommended_distance,
            requires_operator_alert=requires_alert,
            evidence_summary=evidence,
        )

    def build_all(self) -> list[HumanStateResult]:
        results = []
        for person_track_id in list(self._records.keys()):
            result = self.build_human_state(person_track_id)
            if result is not None:
                results.append(result)
        return results

    @property
    def tracked_person_count(self) -> int:
        return len(self._records)
