"""Attributes transcript text to individual diarization segments.

The gap this fills
-------------------
bonbon_speech's STT produces ONE transcript for a whole utterance; its
diarizer produces speaker-attributed time SEGMENTS within that same
utterance. Neither tells you which WORDS belong to which speaker. Re-running
STT per-segment would duplicate the existing speech module.

The fix uses data already available on SpeechTranscription: per-word
timestamps (``words``, ``word_start_times_sec``, ``word_end_times_sec``).
A word is attributed to whichever diarization segment's time window contains
it (with a small boundary slack for STT/diarizer timing jitter). This is
real word-level attribution, not a guess — and when word timestamps aren't
available (some STT backends don't return them), the module is honest about
it: text is only attributed when there is exactly one segment (no ambiguity
possible), otherwise left empty rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DiarizationSegment:
    speaker_id: str
    start_sec: float
    end_sec: float
    confidence: float = 1.0


@dataclass
class WordTiming:
    word: str
    start_sec: float
    end_sec: float
    confidence: float = 1.0


@dataclass
class AttributedSegment:
    segment: DiarizationSegment
    transcript: str
    transcript_confidence: float
    text_is_attributed: bool  # False when attribution was not possible (honest gap)


def attribute_transcript_to_segments(
    segments: list[DiarizationSegment],
    words: list[WordTiming],
    full_text: str,
    full_text_confidence: float,
    boundary_slack_sec: float = 0.15,
) -> list[AttributedSegment]:
    """Splits a whole-utterance transcript across its diarization segments.

    Args:
        segments: This utterance's diarization segments (may be empty).
        words: Per-word timing, in utterance-relative seconds (may be empty
            if the STT backend didn't return word timestamps).
        full_text: The whole-utterance transcript (fallback / single-speaker case).
        full_text_confidence: STT confidence for the whole utterance.
        boundary_slack_sec: Tolerance for a word's timing to fall just outside
            a segment's nominal boundary (STT/diarizer clocks aren't perfectly
            aligned).

    Returns:
        One :class:`AttributedSegment` per input segment, in the same order.
        Empty list if there are no segments.
    """
    if not segments:
        return []

    if len(segments) == 1:
        # No ambiguity — the whole utterance belongs to the only speaker.
        return [
            AttributedSegment(
                segment=segments[0],
                transcript=full_text,
                transcript_confidence=full_text_confidence,
                text_is_attributed=True,
            )
        ]

    if not words:
        # Multiple speakers, no word-level timing available — we genuinely
        # cannot say which words belong to which segment. Report the gap
        # rather than guess (e.g. assigning everything to the dominant speaker
        # would silently misattribute the other speakers' words).
        return [
            AttributedSegment(
                segment=seg,
                transcript="",
                transcript_confidence=0.0,
                text_is_attributed=False,
            )
            for seg in segments
        ]

    results: list[AttributedSegment] = []
    for seg in segments:
        matched_words = [
            w.word
            for w in words
            if w.start_sec >= seg.start_sec - boundary_slack_sec
            and w.end_sec <= seg.end_sec + boundary_slack_sec
        ]
        confidences = [
            w.confidence
            for w in words
            if w.start_sec >= seg.start_sec - boundary_slack_sec
            and w.end_sec <= seg.end_sec + boundary_slack_sec
        ]
        text = " ".join(matched_words).strip()
        conf = sum(confidences) / len(confidences) if confidences else 0.0
        results.append(
            AttributedSegment(
                segment=seg,
                transcript=text,
                transcript_confidence=conf,
                text_is_attributed=bool(text),
            )
        )
    return results
