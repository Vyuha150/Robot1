"""speech_pipeline — orchestrates Phase 6's full chain: ReSpeaker audio
-> VAD/wake-word -> ASR router -> language detector -> transcript
normalizer -> hospital entity correction -> intent detector -> RAG/LLM
gateway -> TTS router -> speaker output.

This module is the GLUE, not a reimplementation: VAD/wake-word gating,
intent detection, and the RAG/LLM gateway are all real, existing
capabilities in bonbon_speech/bonbon_llm that this pipeline calls by
reference (lazy imports, so this package has no hard dependency on ROS2
message types at import time -- consistent with every other module in
this pass). What's new here is ONLY the ordering + the ASR/TTS routing +
the normalization/correction steps this pass adds.
"""

from __future__ import annotations

from dataclasses import dataclass

from bonbon_ai_model_registry.model_registry import ModelRegistry

from bonbon_speech_ai.asr_router import ASRRouter, TranscriptionResult
from bonbon_speech_ai.hospital_entity_corrector import HospitalVocabulary, correct
from bonbon_speech_ai.language_detector import detect
from bonbon_speech_ai.transcript_normalizer import normalize
from bonbon_speech_ai.tts_router import SpeechResult, TTSRouter


@dataclass
class PipelineTurnResult:
    raw_transcript: str
    normalized_transcript: str
    corrected_transcript: str
    language_code: str
    is_code_mixed: bool
    matched_doctor: str | None
    matched_department: str | None
    room_number: str | None
    token_number: str | None
    asr_engine_id: str
    asr_fallback_active: bool


class SpeechPipeline:
    def __init__(self, registry: ModelRegistry, vocabulary: HospitalVocabulary) -> None:
        self._asr = ASRRouter(registry)
        self._tts = TTSRouter(registry)
        self._vocabulary = vocabulary

    def process_utterance(self, audio_path: str, vad_confirmed: bool) -> PipelineTurnResult:
        """Rule: 'ASR must be event-driven after VAD... do not run
        continuous heavy ASR.' `vad_confirmed` must come from a real VAD
        event upstream (bonbon_speech's existing Silero VAD node) -- this
        method refuses to run ASR at all otherwise, rather than trusting
        a caller who skipped the VAD gate."""
        if not vad_confirmed:
            raise ValueError(
                "process_utterance() called without vad_confirmed=True -- ASR must never run continuously, only after a real VAD event"
            )

        asr_result: TranscriptionResult = self._asr.transcribe(audio_path)
        lang = detect(asr_result.text, asr_result.language_code)
        normalized = normalize(
            asr_result.text, lang.language_code, is_code_mixed=lang.is_code_mixed
        )
        entities = correct(normalized, self._vocabulary)

        return PipelineTurnResult(
            raw_transcript=asr_result.text,
            normalized_transcript=normalized,
            corrected_transcript=entities.corrected_text,
            language_code=lang.language_code,
            is_code_mixed=lang.is_code_mixed,
            matched_doctor=entities.matched_doctor,
            matched_department=entities.matched_department,
            room_number=entities.room_number,
            token_number=entities.token_number,
            asr_engine_id=asr_result.engine_model_id,
            asr_fallback_active=asr_result.fallback_active,
        )

    def speak_response(
        self, text: str, language_code: str = "en", phrase_key: str | None = None
    ) -> SpeechResult:
        """Rule: 'TTS must not block safety' -- TTSRouter.speak() already
        never raises (see its own docstring); this method is a thin
        passthrough so callers only need to know about SpeechPipeline,
        not both routers separately."""
        return self._tts.speak(text, language_code, phrase_key)
