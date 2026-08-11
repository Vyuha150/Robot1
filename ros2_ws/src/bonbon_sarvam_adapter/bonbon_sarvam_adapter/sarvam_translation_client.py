"""sarvam_translation_client — dispatches translation to the Edge SDK or
the cloud API depending on the detected mode, or raises honestly if
neither is available. This is the one place callers (e.g. a future
translation router) need to import, rather than choosing edge-vs-api
themselves.
"""

from __future__ import annotations

from bonbon_sarvam_adapter.sarvam_api_client import SarvamAPIClient
from bonbon_sarvam_adapter.sarvam_capability_detector import detect_sarvam_capabilities


class SarvamTranslationUnavailableError(Exception):
    pass


def translate(text: str, source_language_code: str, target_language_code: str) -> str:
    caps = detect_sarvam_capabilities()
    if not caps.available or not caps.translation_available:
        raise SarvamTranslationUnavailableError(
            f"Sarvam translation is not available in this environment ({caps.reason}) -- "
            f"caller must fall back to bonbon_sarvam_adapter.sarvam_fallback_policy's decision, not call this directly"
        )

    if caps.mode == "edge":
        try:
            import sarvam_edge  # type: ignore[import-not-found]
        except ImportError as exc:
            raise SarvamTranslationUnavailableError("Sarvam Edge SDK reported available but is not actually importable") from exc
        engine = sarvam_edge.TranslationEngine()
        return engine.translate(text, source_language_code, target_language_code)

    client = SarvamAPIClient.from_env()
    return client.translate(text, source_language_code, target_language_code)
