"""sarvam_edge_asr_client — wraps a locally-installed Sarvam Edge SDK for
ASR, used ONLY when sarvam_capability_detector confirms mode="edge". No
Edge SDK is installed anywhere in this environment (zero prior Sarvam
integration, confirmed by two independent repo-wide searches) -- this
module's import of the SDK is lazy and only attempted inside
`transcribe()`, so importing this module itself never fails just because
the SDK is absent.
"""

from __future__ import annotations

from dataclasses import dataclass


class SarvamEdgeUnavailableError(Exception):
    pass


@dataclass
class SarvamEdgeASRClient:
    model_variant: str = "saaras-v3"

    def transcribe(self, audio_path: str, language_code: str = "auto") -> str:
        try:
            import sarvam_edge  # type: ignore[import-not-found]
        except ImportError as exc:
            raise SarvamEdgeUnavailableError(
                "Sarvam Edge SDK is not installed in this environment -- caller must check "
                "sarvam_capability_detector.detect_sarvam_capabilities().mode == 'edge' before calling this"
            ) from exc

        # Real call shape depends on the actual Edge SDK's API surface,
        # which this session has never seen installed to verify against.
        # This wrapper exists so the call site (bonbon_speech_ai's ASR
        # router) has one stable interface regardless of which SDK
        # version eventually ships -- update this call once the real SDK
        # is available to test against.
        engine = sarvam_edge.ASREngine(model=self.model_variant)
        return engine.transcribe(audio_path, language=language_code)
