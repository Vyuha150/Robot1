"""TTSRouter — Phase 6's "TTS Router" box. Priority: Sarvam Edge (if
confirmed) -> Piper -> sherpa-onnx -> pre-recorded phrase cache ->
text-only UI fallback. Rule: "TTS must not block safety" -- this router
never raises out of `speak()`; a failure at every tier falls through to
the text-only result rather than propagating an exception into a safety-
relevant code path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from bonbon_ai_model_registry.model_registry import ModelRegistry
from bonbon_ai_model_registry.model_runtime_selector import ModelRuntimeSelector
from bonbon_sarvam_adapter.sarvam_fallback_policy import bespoke_availability_checker

# Frequent hospital phrases cached as audio, keyed by (language, phrase_key)
# -- Phase 6's "cache frequent hospital phrases" requirement. Real audio
# files live under models/tts_cache/<lang>/<key>.wav; this dict just
# names which keys are expected to exist.
HOSPITAL_PHRASE_CACHE_KEYS = (
    "welcome_greeting",
    "token_called",
    "please_wait",
    "follow_me",
    "emergency_staff_alert",
    "navigation_arrived",
)


@dataclass
class SpeechResult:
    audio_path: str | None
    text: str
    engine_model_id: str
    fallback_active: bool
    spoke_audio: bool


class TTSRouter:
    def __init__(self, registry: ModelRegistry) -> None:
        self._registry = registry
        self._selector = ModelRuntimeSelector(
            registry,
            bespoke_checkers={"tts_sarvam_edge": bespoke_availability_checker("tts")},
        )

    def active_engine(self) -> str | None:
        return self._selector.select("tts").decision.active_model_id

    def speak(self, text: str, language_code: str = "en", phrase_key: str | None = None) -> SpeechResult:
        # Event-driven processing rule (Phase 9): "use cached phrase
        # first, synthesize only if cache miss." Checked BEFORE the
        # runtime-selector chain, regardless of which real engine is
        # available -- previously a known cached phrase was still
        # synthesized fresh via Piper/Sarvam every call (measured
        # 2.5-5.8s of real, avoidable latency in this repo's own
        # benchmark runs, see docs/AI_MODEL_BENCHMARK_REPORT.md) because
        # tts_cached_phrase only ever appeared as the second-to-last
        # entry in the availability-based fallback chain, never checked
        # first on its own terms.
        if phrase_key is not None and phrase_key in HOSPITAL_PHRASE_CACHE_KEYS:
            cached_path = self._cached_phrase_path(language_code, phrase_key)
            if cached_path is not None:
                return SpeechResult(cached_path, text, "tts_cached_phrase", False, True)
            # File doesn't exist for this language/phrase yet -- a
            # genuine cache miss, fall through to real synthesis below.

        status = self._selector.select("tts")
        decision = status.decision
        if decision.active_model_id is None or decision.active_model_id == "tts_text_only":
            return SpeechResult(None, text, "tts_text_only", True, False)

        try:
            audio_path = self._invoke(decision.active_model_id, text, language_code, phrase_key)
            return SpeechResult(audio_path, text, decision.active_model_id, decision.fallback_active, True)
        except Exception:  # noqa: BLE001 -- rule: TTS must not block safety; any synthesis failure degrades to text, never raises
            return SpeechResult(None, text, "tts_text_only", True, False)

    @staticmethod
    def _cached_phrase_path(language_code: str, phrase_key: str) -> str | None:
        """Returns the cache file path only if it genuinely exists on
        disk -- never fabricates a path to a file that isn't there
        (that would falsely report spoke_audio=True for silence)."""
        path = f"models/tts_cache/{language_code}/{phrase_key}.wav"
        return path if os.path.isfile(path) else None

    def _invoke(self, model_id: str, text: str, language_code: str, phrase_key: str | None) -> str:
        if model_id == "tts_sarvam_edge":
            from bonbon_sarvam_adapter.sarvam_edge_tts_client import SarvamEdgeTTSClient

            client = SarvamEdgeTTSClient()
            audio = client.synthesize(text, language_code)
            return self._write_temp_audio(audio)

        if model_id in ("tts_piper_en", "tts_piper_hi"):
            import subprocess
            import tempfile

            entry = self._registry.get(model_id)
            # entry.model_name is a human-readable DISPLAY string (e.g.
            # "en_US-lessac-medium (Piper)"), never guaranteed to match
            # the real on-disk filename -- asset_filename is the field
            # that actually does (see model_registry.py's field comment).
            # Falls back to model_name only for older/partial entries
            # that never got asset_filename populated.
            voice_stem = entry.asset_filename or entry.model_name
            out_path = tempfile.mktemp(suffix=".wav")
            subprocess.run(  # noqa: S603 -- piper binary path is fixed, model name is registry-sourced
                ["piper", "--model", f"models/piper/{voice_stem}.onnx", "--output_file", out_path],
                input=text.encode(), capture_output=True, timeout=10.0, check=True,
            )
            return out_path

        if model_id == "tts_cached_phrase":
            if phrase_key not in HOSPITAL_PHRASE_CACHE_KEYS:
                raise ValueError(f"{phrase_key!r} is not a cached phrase -- cache only covers {HOSPITAL_PHRASE_CACHE_KEYS}")
            cached_path = self._cached_phrase_path(language_code, phrase_key)
            if cached_path is None:
                raise FileNotFoundError(f"no cached audio file for phrase_key={phrase_key!r} lang={language_code!r}")
            return cached_path

        raise ValueError(f"no invoker registered for TTS model_id {model_id!r}")

    @staticmethod
    def _write_temp_audio(audio_bytes: bytes) -> str:
        import tempfile

        path = tempfile.mktemp(suffix=".wav")
        with open(path, "wb") as f:
            f.write(audio_bytes)
        return path
