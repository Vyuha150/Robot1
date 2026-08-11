"""Per-tracking-ID temporal smoother using a sliding window average."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Dict

_EMOTION_FIELDS: tuple[str, ...] = (
    "anger",
    "disgust",
    "fear",
    "happiness",
    "sadness",
    "surprise",
    "neutral",
)

# Voice emotion's own category set (VoiceEmotion.msg's *_score fields) --
# a different vocabulary from face's _EMOTION_FIELDS, so this is passed
# explicitly rather than assumed (18-point edge-AI verification, check 9:
# voice emotion previously had no temporal smoothing at all).
VOICE_EMOTION_FIELDS: tuple[str, ...] = (
    "neutral_score",
    "happy_score",
    "sad_score",
    "angry_score",
    "fearful_score",
    "stressed_score",
    "calm_score",
    "urgent_score",
    "confused_score",
)


class TemporalSmoother:
    """Running average over a fixed-length sliding window, keyed by tracking ID.

    Each new raw emotion dictionary is appended to the window for that person's
    tracking ID.  The smoothed result is the element-wise mean across all
    entries in the window.  The dominant emotion is re-derived from the
    averaged scores so that transient peaks do not dominate the output.

    This class is not thread-safe; callers must synchronise access if the
    smoother is shared across threads.
    """

    def __init__(self, window: int = 5, fields: tuple[str, ...] = _EMOTION_FIELDS) -> None:
        """Create a smoother with the given window length.

        Args:
            window: Maximum number of frames to retain per tracking ID.
                Older frames are evicted automatically once the window is full.
            fields: The dict keys to average -- defaults to face emotion's
                category set; pass VOICE_EMOTION_FIELDS for voice emotion
                (a different category vocabulary, e.g. "happy_score" not
                "happiness"). The averaged output only ever carries these
                keys plus dominant_emotion/dominant_confidence, so callers
                with additional non-averaged fields (arousal, valence,
                *_valid flags, etc.) must copy those from `raw` themselves.
        """
        self._window: int = window
        self._fields: tuple[str, ...] = fields
        self._history: Dict[int, deque] = defaultdict(lambda: deque(maxlen=self._window))

    def smooth(self, tracking_id: int, raw: dict) -> dict:
        """Append *raw* to the window for *tracking_id* and return the mean.

        Args:
            tracking_id: Unique integer identifier for the tracked person.
            raw: Dictionary containing per-emotion float scores.  Expected
                keys match this smoother's configured `fields`; missing
                keys default to 0.0.

        Returns:
            dict: Smoothed emotion dictionary with the same keys as *raw* plus
                ``dominant_emotion`` and ``dominant_confidence`` derived from
                the averaged scores.
        """
        self._history[tracking_id].append(raw)
        window: deque = self._history[tracking_id]

        if not window:
            return raw

        result: dict = {}
        for field in self._fields:
            vals: list[float] = [float(d.get(field, 0.0)) for d in window]
            result[field] = sum(vals) / len(vals)

        # Re-derive dominant emotion from averaged scores. Field names like
        # voice's "happy_score" carry a "_score" suffix the emitted label
        # must not (VoiceEmotion.msg.dominant_emotion expects "happy", not
        # "happy_score") -- stripping it is a no-op for face's suffix-free
        # field names, so this is safe for both smoothers.
        dominant: str = max(self._fields, key=lambda f: result[f])
        result["dominant_emotion"] = dominant.removesuffix("_score")
        result["dominant_confidence"] = result[dominant]
        return result

    def reset(self, tracking_id: int) -> None:
        """Clear the history for a specific tracking ID.

        Args:
            tracking_id: The tracking ID whose history should be cleared.
        """
        if tracking_id in self._history:
            self._history[tracking_id].clear()

    def purge_all(self) -> None:
        """Clear the history for all tracking IDs."""
        self._history.clear()

    @property
    def window_size(self) -> int:
        """Return the configured window length."""
        return self._window
