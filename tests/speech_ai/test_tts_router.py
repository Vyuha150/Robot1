"""Tests for bonbon_speech_ai.tts_router.TTSRouter -- priority chain
(Sarvam Edge -> Piper -> sherpa-onnx -> cached phrase -> text-only), and
the "TTS must never block safety" rule: speak() must never raise out of
synthesis failure, it must always degrade to a text-only SpeechResult."""

from __future__ import annotations

import unittest
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "models" / "model_registry.yaml"


class TestTTSRouterOnThisSandbox(unittest.TestCase):
    """Whatever the real chain resolves to on THIS machine. As of this
    pass, piper-tts + the real en_US-lessac-medium voice file are
    installed here, so speak() genuinely synthesizes audio -- assertions
    below check invariants that hold either way (never raises, never
    fabricates when nothing works) rather than assuming a fixed engine."""

    def setUp(self):
        from bonbon_ai_model_registry.model_registry import ModelRegistry
        from bonbon_speech_ai.tts_router import TTSRouter

        self.registry = ModelRegistry.load(REGISTRY_PATH)
        self.router = TTSRouter(self.registry)

    def test_speak_never_raises_regardless_of_which_tier_is_active(self):
        try:
            result = self.router.speak("Welcome to City Hospital.", "en", phrase_key="welcome_greeting")
        except Exception as exc:  # noqa: BLE001
            self.fail(f"speak() must never raise -- TTS failures must degrade to text, not block safety: {exc!r}")
        self.assertEqual(result.text, "Welcome to City Hospital.")

    def test_synthesis_failure_degrades_to_text_only_even_when_selector_reports_available(self):
        # Structural safety-contract test, independent of what's actually
        # installed: force _invoke to raise (corrupt voice file, engine
        # crash, subprocess timeout -- any real-world failure mode) and
        # confirm speak() still degrades to text-only rather than
        # propagating the exception. This is the regression coverage the
        # old environment-dependent version of this test used to provide
        # only by accident (because nothing was installed); it now holds
        # regardless of environment.
        from unittest.mock import patch

        with patch.object(self.router, "_invoke", side_effect=RuntimeError("simulated synthesis failure")):
            result = self.router.speak("Some arbitrary sentence.", "en", phrase_key=None)
        self.assertFalse(result.spoke_audio)
        self.assertIsNone(result.audio_path)
        self.assertEqual(result.engine_model_id, "tts_text_only")
        self.assertTrue(result.fallback_active)

    def test_cached_phrase_key_must_be_a_known_hospital_phrase(self):
        from bonbon_speech_ai.tts_router import HOSPITAL_PHRASE_CACHE_KEYS

        self.assertIn("welcome_greeting", HOSPITAL_PHRASE_CACHE_KEYS)
        self.assertIn("emergency_staff_alert", HOSPITAL_PHRASE_CACHE_KEYS)

    def test_cache_miss_for_a_known_phrase_key_falls_through_to_real_synthesis(self):
        # A known phrase key with no cache file on disk must never claim
        # a cache hit -- it falls through to the normal engine chain
        # instead (still resolves to SOME result, never raises).
        from unittest.mock import patch

        with patch.object(self.router, "_cached_phrase_path", return_value=None):
            result = self.router.speak("Welcome.", "en", phrase_key="welcome_greeting")
        self.assertNotEqual(result.engine_model_id, "tts_cached_phrase")


class TestCachedPhraseCheckedBeforeSynthesis(unittest.TestCase):
    """Event-driven processing rule (Phase 9): "use cached phrase first,
    synthesize only if cache miss." Uses a real temp file under
    models/tts_cache/ (the exact path TTSRouter reads) so this is a real
    file-presence check, not a mock of the cache lookup itself."""

    _LANG = "test-cache-first"
    _PHRASE_KEY = "welcome_greeting"

    def setUp(self):
        import os

        from bonbon_ai_model_registry.model_registry import ModelRegistry
        from bonbon_speech_ai.tts_router import TTSRouter

        self.registry = ModelRegistry.load(REGISTRY_PATH)
        self.router = TTSRouter(self.registry)
        # Forward slashes deliberately -- matches TTSRouter._cached_phrase_path's
        # own hardcoded f"models/tts_cache/{lang}/{key}.wav" format exactly,
        # since that's the string the router will actually return.
        self._cache_dir = f"models/tts_cache/{self._LANG}"
        os.makedirs(self._cache_dir, exist_ok=True)
        self._cache_path = f"{self._cache_dir}/{self._PHRASE_KEY}.wav"
        with open(self._cache_path, "wb") as f:
            f.write(b"RIFF\x00\x00\x00\x00WAVEfake")

    def tearDown(self):
        import os
        import shutil

        if os.path.isfile(self._cache_path):
            os.remove(self._cache_path)
        shutil.rmtree(self._cache_dir, ignore_errors=True)

    def test_cache_hit_returns_immediately_without_touching_the_runtime_selector(self):
        from unittest.mock import patch

        with patch.object(self.router, "_selector") as mock_selector:
            result = self.router.speak("Welcome to City Hospital.", self._LANG, phrase_key=self._PHRASE_KEY)
            mock_selector.select.assert_not_called()
        self.assertTrue(result.spoke_audio)
        self.assertEqual(result.engine_model_id, "tts_cached_phrase")
        self.assertEqual(result.audio_path, self._cache_path)
        self.assertFalse(result.fallback_active)


class TestRealPiperSynthesisWhenInstalled(unittest.TestCase):
    """Only meaningful (and only runs its real assertions) when piper-tts
    AND a real voice .onnx file are actually present -- SKIPs honestly
    otherwise rather than asserting real-audio behavior against a mock.
    Confirms the asset_filename fix: entry.model_name is a display string
    ("en_US-lessac-medium (Piper)"), never a real filename -- TTSRouter
    must use entry.asset_filename to locate the downloaded voice file."""

    def setUp(self):
        import importlib.util
        import shutil
        from pathlib import Path

        from bonbon_ai_model_registry.model_registry import ModelRegistry
        from bonbon_speech_ai.tts_router import TTSRouter

        self.registry = ModelRegistry.load(REGISTRY_PATH)
        self.router = TTSRouter(self.registry)
        entry = self.registry.get("tts_piper_en")
        voice_path = Path(__file__).resolve().parents[2] / "models" / "piper" / f"{entry.asset_filename}.onnx"
        if importlib.util.find_spec("piper") is None or not voice_path.is_file() or shutil.which("piper") is None:
            self.skipTest(
                "piper-tts package, the real en_US-lessac-medium.onnx voice file, and/or the "
                "`piper` CLI on PATH are not all present -- BLOCKED, not failed. "
                "(The CLI is installed to <venv>/Scripts or <venv>/bin -- make sure that's on PATH.)"
            )

    def test_asset_filename_is_populated_and_differs_from_the_display_model_name(self):
        entry = self.registry.get("tts_piper_en")
        self.assertEqual(entry.asset_filename, "en_US-lessac-medium")
        self.assertNotEqual(entry.asset_filename, entry.model_name)

    def test_real_synthesis_produces_a_playable_wav_file(self):
        import os

        result = self.router.speak("Welcome to City Hospital, how can I help you today?", "en")
        self.assertTrue(result.spoke_audio)
        self.assertEqual(result.engine_model_id, "tts_piper_en")
        self.assertIsNotNone(result.audio_path)
        self.assertTrue(os.path.isfile(result.audio_path))
        with open(result.audio_path, "rb") as f:
            header = f.read(12)
        self.assertEqual(header[:4], b"RIFF")
        self.assertEqual(header[8:12], b"WAVE")


class TestTTSRouterFallbackChainOrder(unittest.TestCase):
    def setUp(self):
        from bonbon_ai_model_registry.model_registry import ModelRegistry

        self.registry = ModelRegistry.load(REGISTRY_PATH)

    def test_configured_chain_matches_the_brief_priority_order(self):
        chain = [e.model_id for e in self.registry.fallback_chain("tts_sarvam_edge")]
        self.assertEqual(
            chain,
            ["tts_sarvam_edge", "tts_piper_en", "tts_sherpa_onnx", "tts_cached_phrase", "tts_text_only"],
        )


if __name__ == "__main__":
    unittest.main()
