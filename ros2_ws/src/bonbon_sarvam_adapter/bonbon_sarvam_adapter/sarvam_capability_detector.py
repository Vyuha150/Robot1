"""sarvam_capability_detector — the single real-detection entry point
every other module in this package (and scripts/ai_models/check_sarvam_access.py,
and the Phase 11 dashboard endpoints) calls. Never assumes access; only
ever reports what it can actually observe in this environment (an
importable Edge package, or an API key + explicit cloud-enable flag).
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass, field

from bonbon_sarvam_adapter.sarvam_license_status import SarvamLicenseStatus, evaluate

# Package names an official Sarvam Edge SDK might install under -- kept as
# a list, not a single guess, since this session has no way to confirm
# the real package name (zero prior integration anywhere in this repo).
# Both are checked; neither is assumed to exist.
_CANDIDATE_EDGE_PACKAGE_NAMES = ("sarvam_edge", "sarvam")


@dataclass
class SarvamCapabilities:
    available: bool
    mode: str  # "edge" | "api" | "unavailable"
    reason: str
    asr_available: bool = False
    tts_available: bool = False
    translation_available: bool = False
    ocr_available: bool = False
    languages_supported: list[str] = field(default_factory=list)
    fallback_active: bool = True

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "mode": self.mode,
            "reason": self.reason,
            "asrAvailable": self.asr_available,
            "ttsAvailable": self.tts_available,
            "translationAvailable": self.translation_available,
            "ocrAvailable": self.ocr_available,
            "languagesSupported": self.languages_supported,
            "fallbackActive": self.fallback_active,
        }


def _find_edge_package() -> str | None:
    for name in _CANDIDATE_EDGE_PACKAGE_NAMES:
        if importlib.util.find_spec(name) is not None:
            return name
    return None


def detect_license_status() -> SarvamLicenseStatus:
    edge_package = _find_edge_package()
    api_key_present = bool(os.environ.get("SARVAM_API_KEY", ""))
    cloud_enabled = os.environ.get("BONBON_CLOUD_ENABLED", "false").lower() == "true"
    return evaluate(edge_installed=edge_package is not None, api_key_present=api_key_present, cloud_enabled=cloud_enabled)


def detect_sarvam_capabilities() -> SarvamCapabilities:
    """The real, callable detector. Capability granularity (ASR/TTS/
    translation/OCR) cannot be introspected without a real Edge SDK to
    query -- when access IS confirmed, this reports the capabilities
    Sarvam's own public documentation names for Saaras/Bulbul (ASR/TTS/
    translation), with OCR only if an explicit env flag opts in (OCR
    access terms are a separate, unconfirmed question this pass cannot
    resolve). When access is NOT confirmed, every capability is False --
    never optimistically assumed."""
    status = detect_license_status()

    if not status.allowed:
        return SarvamCapabilities(available=False, mode=status.mode, reason=status.reason, fallback_active=True)

    ocr_opt_in = os.environ.get("SARVAM_OCR_ENABLED", "false").lower() == "true"
    return SarvamCapabilities(
        available=True,
        mode=status.mode,
        reason=status.reason,
        asr_available=True,
        tts_available=True,
        translation_available=True,
        ocr_available=ocr_opt_in,
        languages_supported=["en", "hi", "te"],
        fallback_active=False,
    )
