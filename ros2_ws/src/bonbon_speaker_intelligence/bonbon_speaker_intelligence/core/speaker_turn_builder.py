"""Orchestrator: turns one utterance's transcription + diarization output into
one or more SpeakerTurnResult records — the pure-Python shape that
speaker_intelligence_node converts 1:1 into SpeakerTurn ROS messages.

Ties together (without re-deriving any of them):
  - transcript_segment_mapper  -> per-segment transcript text
  - speaker_identity_manager   -> persistent speaker_id
  - audio_visual_associator    -> linked person_track_id
  - voice_emotion_cache        -> latest voice emotion reading

Honest handling of overlapping speech: a single DOA reading describes the
WHOLE utterance, not each segment. Only the dominant (first/longest) segment
gets real identity continuity from SpeakerIdentityManager; any additional
segment in the same overlapping utterance is given a fresh, non-continuous
identity (we have no signal to do better) and the whole utterance's turns
are flagged is_overlapping=True so downstream consumers treat the
association and continuity claims with appropriate caution.
"""

from __future__ import annotations

from dataclasses import dataclass

from bonbon_speaker_intelligence.core.audio_visual_associator import (
    TrackedPersonBearing,
    associate_doa_to_person,
)
from bonbon_speaker_intelligence.core.speaker_identity_manager import SpeakerIdentityManager
from bonbon_speaker_intelligence.core.transcript_segment_mapper import (
    DiarizationSegment,
    WordTiming,
    attribute_transcript_to_segments,
)
from bonbon_speaker_intelligence.core.voice_emotion_cache import VoiceEmotionCache

_UNKNOWN_DOA_DEG = -1.0


@dataclass
class SpeakerTurnResult:
    speaker_id: str
    person_track_id: str
    association_confidence: float
    start_time_sec: float
    end_time_sec: float
    transcript: str
    transcript_confidence: float
    voice_emotion: str
    emotion_confidence: float
    audio_source_direction_deg: float
    is_new_speaker: bool
    is_overlapping: bool
    is_off_camera: bool
    noisy_audio: bool
    short_segment: bool


class SpeakerTurnBuilder:
    def __init__(
        self,
        identity_manager: SpeakerIdentityManager,
        voice_emotion_cache: VoiceEmotionCache,
        short_segment_threshold_sec: float = 0.3,
        max_bearing_delta_deg: float = 25.0,
    ) -> None:
        self._identity = identity_manager
        self._voice_cache = voice_emotion_cache
        self._short_segment_threshold = short_segment_threshold_sec
        self._max_bearing_delta = max_bearing_delta_deg

    def build_turns(
        self,
        segments: list[DiarizationSegment],
        words: list[WordTiming],
        full_text: str,
        full_text_confidence: float,
        doa_deg: float,
        tracked_persons: list[TrackedPersonBearing],
        noisy_audio: bool = False,
    ) -> list[SpeakerTurnResult]:
        if not segments:
            return []

        attributed = attribute_transcript_to_segments(
            segments, words, full_text, full_text_confidence
        )
        is_overlapping = len(segments) > 1
        voice_emotion, emotion_conf = self._voice_cache.get_if_fresh()

        results: list[SpeakerTurnResult] = []
        for i, att in enumerate(attributed):
            # Only the first (dominant) segment gets real DOA-based identity
            # continuity; additional overlapping segments get a fresh,
            # non-continuous identity rather than a falsely-confident reuse.
            resolve_doa = doa_deg if i == 0 else _UNKNOWN_DOA_DEG
            speaker_id, is_new = self._identity.resolve(resolve_doa)

            assoc = associate_doa_to_person(
                doa_deg, tracked_persons, max_bearing_delta_deg=self._max_bearing_delta
            )
            assoc_confidence = assoc.confidence
            if is_overlapping:
                # We can't be sure DOA describes THIS particular segment when
                # multiple people spoke in the same utterance.
                assoc_confidence *= 0.5

            duration = att.segment.end_sec - att.segment.start_sec
            results.append(
                SpeakerTurnResult(
                    speaker_id=speaker_id,
                    person_track_id=assoc.person_track_id if assoc.matched else "",
                    association_confidence=assoc_confidence if assoc.matched else 0.0,
                    start_time_sec=att.segment.start_sec,
                    end_time_sec=att.segment.end_sec,
                    transcript=att.transcript,
                    transcript_confidence=att.transcript_confidence,
                    voice_emotion=voice_emotion,
                    emotion_confidence=emotion_conf,
                    audio_source_direction_deg=doa_deg,
                    is_new_speaker=is_new,
                    is_overlapping=is_overlapping,
                    is_off_camera=not assoc.matched,
                    noisy_audio=noisy_audio,
                    short_segment=duration < self._short_segment_threshold,
                )
            )
        return results
