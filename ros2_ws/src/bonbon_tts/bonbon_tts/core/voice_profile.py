"""
bonbon_tts.core.voice_profile
================================
VoiceProfileManager — multilingual voice selection and emotion-aware
speech style adjustment.

Design goals
------------
- **Multilingual-ready**: each language maps to one ``VoiceProfile``
  (Piper model + speed settings).  Adding a language only requires
  registering a new ``VoiceProfile``; no other code changes.
- **Emotion-aware**: ``apply_emotion()`` modifies ``length_scale`` and
  the future ``pitch_scale`` based on a named emotion, letting the LLM
  pass emotion hints that translate to audible speech style differences.
- **Offline-first**: all model paths are local; no network needed.

Supported emotions (length_scale modifiers)
--------------------------------------------
neutral   1.00   calm      1.10   friendly  1.00
happy     0.93   sad       1.20   urgent    0.80
excited   0.85   angry     0.88   whisper   1.15
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, replace

logger = logging.getLogger(__name__)


# ── Emotion table ──────────────────────────────────────────────────────────────

_EMOTION_LENGTH_SCALE: dict[str, float] = {
    "neutral": 1.00,
    "happy": 0.93,
    "excited": 0.85,
    "calm": 1.10,
    "sad": 1.20,
    "urgent": 0.80,
    "friendly": 1.00,
    "angry": 0.88,
    "whisper": 1.15,
}

DEFAULT_EMOTION = "neutral"


# ── Voice profile ──────────────────────────────────────────────────────────────


@dataclass
class VoiceProfile:
    """
    Configuration for a single language / voice combination.

    Parameters
    ----------
    language:
        BCP-47 language tag (e.g. ``"en"``, ``"ja"``, ``"de"``).
    voice_id:
        Human-readable Piper voice name
        (e.g. ``"en_US-lessac-medium"``).
    model_path:
        Absolute path to the ``.onnx`` model file.
        Empty string → Piper will look for the voice by ``voice_id``.
    length_scale:
        Base speaking rate.  1.0 = natural speed.
    noise_scale:
        Phoneme duration noise.  Passed to Piper unchanged.
    description:
        Optional human-readable note.
    """

    language: str = "en"
    voice_id: str = "en_US-lessac-medium"
    model_path: str = ""
    length_scale: float = 1.0
    noise_scale: float = 0.667
    description: str = ""


# ── Manager ────────────────────────────────────────────────────────────────────


class VoiceProfileManager:
    """
    Manages voice profiles for multilingual and emotion-aware speech.

    Usage::

        mgr = VoiceProfileManager()
        mgr.add_profile(VoiceProfile(language="ja",
                                     voice_id="ja_JP-kenichi-medium"))

        profile = mgr.get_profile("ja")
        styled  = mgr.apply_emotion(profile, "excited")
        # styled.length_scale is now 0.85 × profile.length_scale

    Parameters
    ----------
    profiles:
        Optional pre-seeded ``{language: VoiceProfile}`` dict.
        An English default is always registered.
    """

    def __init__(
        self,
        profiles: dict[str, VoiceProfile] | None = None,
    ) -> None:
        self._profiles: dict[str, VoiceProfile] = {}
        self._language = "en"

        # Always register the English default
        self._profiles["en"] = VoiceProfile(
            language="en",
            voice_id="en_US-lessac-medium",
            length_scale=1.0,
            description="Default English (US) voice",
        )
        if profiles:
            for lang, profile in profiles.items():
                self._profiles[lang] = profile

    # ── Registration ──────────────────────────────────────────────────────────

    def add_profile(self, profile: VoiceProfile) -> None:
        """Register or replace a voice profile."""
        self._profiles[profile.language] = profile
        logger.info(
            "VoiceProfileManager: registered profile lang=%r voice=%r",
            profile.language,
            profile.voice_id,
        )

    # ── Lookup ────────────────────────────────────────────────────────────────

    def get_profile(self, language: str | None = None) -> VoiceProfile:
        """
        Return the profile for *language*, falling back to English.

        Parameters
        ----------
        language:
            BCP-47 code (e.g. ``"en"``, ``"de"``).
            ``None`` uses the current active language.
        """
        lang = language or self._language
        profile = self._profiles.get(lang)
        if profile is None:
            logger.warning(
                "VoiceProfileManager: no profile for language=%r, falling back to English",
                lang,
            )
            profile = self._profiles["en"]
        return profile

    # ── Language selection ────────────────────────────────────────────────────

    def set_language(self, language: str) -> bool:
        """
        Set the active language.

        Returns
        -------
        bool
            True if the language is supported (profile exists), False otherwise.
            Even when False the language is stored (profile falls back to English).
        """
        supported = language in self._profiles
        self._language = language
        if not supported:
            logger.warning(
                "VoiceProfileManager: language=%r not supported — will use English",
                language,
            )
        else:
            logger.info("VoiceProfileManager: language set to %r", language)
        return supported

    # ── Emotion style ─────────────────────────────────────────────────────────

    def apply_emotion(
        self,
        profile: VoiceProfile,
        emotion: str,
    ) -> VoiceProfile:
        """
        Return a *copy* of *profile* with ``length_scale`` adjusted for *emotion*.

        Parameters
        ----------
        profile:
            The base voice profile to modify.
        emotion:
            Named emotion (e.g. ``"happy"``, ``"urgent"``).
            Unknown emotions produce a warning and return the profile unchanged.

        Returns
        -------
        VoiceProfile
            A new ``VoiceProfile`` instance; the original is not mutated.
        """
        emotion_lc = emotion.lower().strip()
        modifier = _EMOTION_LENGTH_SCALE.get(emotion_lc)
        if modifier is None:
            logger.warning(
                "VoiceProfileManager: unknown emotion %r — ignoring",
                emotion,
            )
            return copy.copy(profile)

        adjusted = replace(
            profile,
            length_scale=round(profile.length_scale * modifier, 4),
        )
        logger.debug(
            "VoiceProfileManager: emotion=%r length_scale %.3f → %.3f",
            emotion,
            profile.length_scale,
            adjusted.length_scale,
        )
        return adjusted

    # ── Inspection ────────────────────────────────────────────────────────────

    @property
    def current_language(self) -> str:
        return self._language

    @property
    def supported_languages(self) -> list[str]:
        """List of registered language codes."""
        return list(self._profiles.keys())

    def has_language(self, language: str) -> bool:
        return language in self._profiles
