"""ASRRouter — Phase 6's "ASR Router" box. Decides which ASR backend
actually runs, in priority order: Sarvam Edge (if real access confirmed)
-> faster-whisper (the real, already-deployed choice) -> sherpa-onnx ->
whisper.cpp -> degraded template input. Never runs continuous ASR --
callers must gate calls on a real VAD/wake-word event first (this
router does not do that itself; see bonbon_speech's existing VAD/wake-
word nodes, which this package does not duplicate).
"""

from __future__ import annotations

from dataclasses import dataclass

from bonbon_ai_model_registry.model_registry import ModelRegistry
from bonbon_ai_model_registry.model_runtime_selector import ModelRuntimeSelector
from bonbon_sarvam_adapter.sarvam_fallback_policy import bespoke_availability_checker


@dataclass
class TranscriptionResult:
    text: str
    engine_model_id: str
    language_code: str
    confidence: float
    fallback_active: bool


class ASRRouter:
    def __init__(self, registry: ModelRegistry) -> None:
        self._registry = registry
        self._selector = ModelRuntimeSelector(
            registry,
            bespoke_checkers={"asr_sarvam_edge": bespoke_availability_checker("asr")},
        )

    def active_engine(self) -> str | None:
        status = self._selector.select("asr")
        return status.decision.active_model_id

    def transcribe(self, audio_path: str, expected_language: str | None = None) -> TranscriptionResult:
        status = self._selector.select("asr")
        decision = status.decision
        if decision.active_model_id is None or decision.active_model_id == "asr_degraded_template":
            # Terminal fallback: no real ASR engine available (either the
            # whole chain was exhausted, or it correctly resolved to the
            # always-available degraded_template entry). Never fabricate
            # a transcript -- hand back an empty, explicitly marked
            # result so the caller routes to typed/touch input.
            return TranscriptionResult("", "asr_degraded_template", expected_language or "unknown", 0.0, True)

        entry = self._registry.get(decision.active_model_id)
        try:
            text, confidence = self._invoke(entry.model_id, entry.provider, audio_path, expected_language)
        except Exception:  # noqa: BLE001 -- an ASR engine the selector resolved as "available" (package importable)
            # can still fail to actually invoke (e.g. no model file selected
            # yet, see GAP-7) -- must degrade to an honest empty transcript,
            # never crash the caller. Same rule TTSRouter.speak() already
            # follows; this was a real bug (uncaught crash) until fixed.
            return TranscriptionResult("", entry.model_id, expected_language or "unknown", 0.0, True)
        return TranscriptionResult(text, entry.model_id, expected_language or "auto", confidence, decision.fallback_active)

    def _invoke(self, model_id: str, provider: str, audio_path: str, language: str | None) -> tuple[str, float]:
        if model_id == "asr_sarvam_edge":
            from bonbon_sarvam_adapter.sarvam_edge_asr_client import SarvamEdgeASRClient

            client = SarvamEdgeASRClient()
            return client.transcribe(audio_path, language or "auto"), 0.9

        if model_id == "asr_faster_whisper":
            from faster_whisper import WhisperModel  # type: ignore[import-not-found]

            model = WhisperModel("base")
            segments, info = model.transcribe(audio_path, language=language)
            text = " ".join(s.text.strip() for s in segments)
            return text, float(getattr(info, "language_probability", 0.0) or 0.0)

        if model_id == "asr_sherpa_onnx":
            import sherpa_onnx  # type: ignore[import-not-found]  # noqa: F401

            raise NotImplementedError("sherpa-onnx ASR invocation requires a selected model file -- not yet benchmarked/selected, see GAP-7")

        if model_id == "asr_whisper_cpp":
            raise NotImplementedError("whisper.cpp invocation requires the compiled binary path -- see scripts/ai_models/install_whisper_cpp.sh")

        raise ValueError(f"no invoker registered for ASR model_id {model_id!r}")
