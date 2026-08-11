"""sarvam_fallback_policy — the ONE decision function bonbon_speech_ai's
ASR/TTS routers (Phase 6) call to decide "use Sarvam, or fall back."
Wraps bonbon_ai_model_registry's generic FallbackPolicy with the
Sarvam-specific availability check (sarvam_capability_detector) rather
than a generic pip/ollama check -- this is the "bespoke_checker" the
generic ModelRuntimeSelector expects for provider="sarvam" entries.
"""

from __future__ import annotations

from dataclasses import dataclass

from bonbon_sarvam_adapter.sarvam_capability_detector import SarvamCapabilities, detect_sarvam_capabilities


@dataclass
class SarvamRoutingDecision:
    capability: str
    use_sarvam: bool
    reason: str
    fallback_active: bool


def decide(capability: str) -> SarvamRoutingDecision:
    """capability is one of "asr" | "tts" | "translation" -- checked
    against the specific sub-capability flag on SarvamCapabilities so a
    partially-available Sarvam integration (e.g. ASR confirmed but OCR
    not opted in) is never conflated into one blanket yes/no."""
    caps: SarvamCapabilities = detect_sarvam_capabilities()

    flag_by_capability = {
        "asr": caps.asr_available,
        "tts": caps.tts_available,
        "translation": caps.translation_available,
    }
    supported = flag_by_capability.get(capability)
    if supported is None:
        return SarvamRoutingDecision(capability, False, f"Sarvam does not offer a {capability!r} capability", True)

    if not caps.available:
        return SarvamRoutingDecision(capability, False, caps.reason, True)

    if not supported:
        return SarvamRoutingDecision(capability, False, f"Sarvam is available ({caps.mode}) but {capability} was not reported as supported", True)

    return SarvamRoutingDecision(capability, True, f"Sarvam {caps.mode} confirmed available for {capability}", False)


def bespoke_availability_checker(sarvam_capability: str):
    """Returns a zero-arg callable suitable for passing into
    bonbon_ai_model_registry.ModelRuntimeSelector's `bespoke_checkers`
    dict, keyed by the relevant sarvam_* model_id -- e.g.:

        ModelRuntimeSelector(registry, bespoke_checkers={
            "asr_sarvam_edge": bespoke_availability_checker("asr"),
            "tts_sarvam_edge": bespoke_availability_checker("tts"),
            "translation_sarvam": bespoke_availability_checker("translation"),
        })

    This is the wiring point that makes the generic registry's
    fallback-chain resolution honestly reflect real Sarvam availability
    instead of the registry's own generic (and wrong-for-Sarvam)
    external_api heuristic.
    """

    def _check(_entry) -> bool:  # noqa: ANN001 -- entry type is ModelEntry, kept untyped to avoid a hard dependency edge back to bonbon_ai_model_registry's types in this signature
        return decide(sarvam_capability).use_sarvam

    return _check
