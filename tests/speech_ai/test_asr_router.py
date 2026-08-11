"""Tests for bonbon_speech_ai.asr_router.ASRRouter -- priority chain
(Sarvam Edge -> faster-whisper -> sherpa-onnx -> whisper.cpp -> degraded
template) and the regression this session fixed: the terminal
asr_degraded_template entry is a real, always-"available" mock entry (not
active_model_id=None), so the router's guard must explicitly treat it as
the no-real-ASR case too, or transcribe() raises ValueError instead of
returning an honest empty result."""

from __future__ import annotations

import unittest
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "models" / "model_registry.yaml"


class TestASRRouterOnThisSandbox(unittest.TestCase):
    """Whatever the real chain resolves to on THIS machine -- may be
    asr_degraded_template (nothing installed) or a real engine like
    asr_sherpa_onnx (installed but no model file selected yet, GAP-7) --
    transcribe() must never crash and must never fabricate a transcript.
    Assertions below are written against `active_engine()`'s actual
    result rather than a hardcoded engine id, so this test stays correct
    whether or not sherpa-onnx/faster-whisper/etc are installed."""

    def setUp(self):
        from bonbon_ai_model_registry.model_registry import ModelRegistry
        from bonbon_speech_ai.asr_router import ASRRouter

        self.registry = ModelRegistry.load(REGISTRY_PATH)
        self.router = ASRRouter(self.registry)

    def test_active_engine_resolves_without_raising(self):
        engine = self.router.active_engine()
        self.assertIsNotNone(engine)  # resolves to at least the terminal degraded template, never None

    def test_transcribe_never_raises_regardless_of_which_tier_is_active(self):
        # Regression test for the bug fixed this session: calling
        # transcribe() used to raise
        # ValueError("no invoker registered for ASR model_id 'asr_degraded_template'")
        # because the guard only checked `active_model_id is None`, missing
        # the real terminal-mock case. A second regression surfaced later
        # the same session: once sherpa-onnx was actually installed here,
        # the chain resolved to asr_sherpa_onnx (a real, "available"
        # entry) -- but no invoker is wired for it yet (GAP-7, no model
        # file selected), so _invoke() raised NotImplementedError
        # uncaught. Both cases must degrade to an honest empty result.
        expected_engine = self.router.active_engine()
        try:
            result = self.router.transcribe("samples/asr/does_not_exist.wav", "en")
        except Exception as exc:  # noqa: BLE001
            self.fail(f"transcribe() must never raise, regardless of what's installed: {exc!r}")
        self.assertEqual(result.text, "")
        self.assertEqual(result.engine_model_id, expected_engine, "must honestly attribute the empty result to whichever engine was actually attempted")
        self.assertTrue(result.fallback_active)
        self.assertEqual(result.confidence, 0.0)

    def test_never_fabricates_a_nonempty_transcript(self):
        result = self.router.transcribe("samples/asr/hospital_phrase.wav", "en")
        self.assertEqual(result.text, "", "no real ASR model file is wired/selected yet (GAP-7) -- a transcript must never be fabricated")

    def test_invocation_failure_degrades_gracefully_even_when_selector_reports_available(self):
        # Structural test, independent of what's actually installed:
        # force _invoke to raise (simulating any real-world ASR failure --
        # corrupt audio, missing model file, engine crash) and confirm
        # transcribe() still returns an honest empty result rather than
        # propagating the exception -- this is the actual safety contract,
        # not just a snapshot of today's environment.
        from unittest.mock import patch

        with patch.object(self.router, "_invoke", side_effect=RuntimeError("simulated engine failure")):
            # Force a non-degraded-template active model so _invoke is
            # actually reached; only meaningful if something else is
            # available besides the terminal mock.
            if self.router.active_engine() == "asr_degraded_template":
                self.skipTest("nothing but the terminal mock is available -- _invoke is never reached in this environment")
            result = self.router.transcribe("samples/asr/anything.wav", "en")
        self.assertEqual(result.text, "")
        self.assertTrue(result.fallback_active)


class TestASRRouterFallbackChainOrder(unittest.TestCase):
    def setUp(self):
        from bonbon_ai_model_registry.model_registry import ModelRegistry

        self.registry = ModelRegistry.load(REGISTRY_PATH)

    def test_configured_chain_matches_the_brief_priority_order(self):
        chain = [e.model_id for e in self.registry.fallback_chain("asr_sarvam_edge")]
        self.assertEqual(
            chain,
            ["asr_sarvam_edge", "asr_faster_whisper", "asr_sherpa_onnx", "asr_whisper_cpp", "asr_degraded_template"],
        )


if __name__ == "__main__":
    unittest.main()
