"""sarvam_edge_tts_client — Edge-SDK TTS wrapper, same lazy-import and
"unverified until a real SDK exists to test against" posture as
sarvam_edge_asr_client.py. See that module's docstring for the full
rationale -- not repeated here.
"""

from __future__ import annotations

from dataclasses import dataclass


class SarvamEdgeUnavailableError(Exception):
    pass


@dataclass
class SarvamEdgeTTSClient:
    voice_variant: str = "bulbul-v3"

    def synthesize(self, text: str, language_code: str, speaker: str = "meera") -> bytes:
        try:
            import sarvam_edge  # type: ignore[import-not-found]
        except ImportError as exc:
            raise SarvamEdgeUnavailableError(
                "Sarvam Edge SDK is not installed in this environment -- caller must check "
                "sarvam_capability_detector.detect_sarvam_capabilities().mode == 'edge' before calling this"
            ) from exc

        engine = sarvam_edge.TTSEngine(model=self.voice_variant)
        return engine.synthesize(text, language=language_code, speaker=speaker)
