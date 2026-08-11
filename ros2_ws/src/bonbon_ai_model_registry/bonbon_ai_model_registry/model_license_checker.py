"""LicenseChecker — the gate every download must pass through before
model_downloader.py is allowed to run a download_command. Encodes rules
1-3 from the AI model upgrade brief: never fake availability, never
download without checking license+storage, never download Sarvam/other
commercial models without confirmed official access.

This module makes no network calls and touches no disk beyond reading
the registry -- it is a pure decision function, deliberately easy to
unit-test without any hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from bonbon_ai_model_registry.model_registry import ModelEntry

# Providers that must never auto-download without an explicit, externally
# supplied "official access confirmed" check -- Sarvam by name (rule 3/12),
# plus any provider whose commercial_allowed status this registry cannot
# resolve on its own (Porcupine's conditional free tier, Indic TTS models
# with per-release licensing, InsightFace's restricted pretrained weights --
# see docs/AI_MODEL_DOWNLOAD_AND_LICENSE_PLAN.md).
_GATED_PROVIDERS = frozenset({"sarvam"})


@dataclass
class LicenseDecision:
    model_id: str
    allowed: bool
    reason: str


class LicenseChecker:
    def __init__(
        self,
        max_storage_mb: int = 2048,
        access_checkers: dict[str, Callable[[], bool]] | None = None,
    ) -> None:
        """`access_checkers` maps a provider name (e.g. "sarvam") to a
        zero-arg callable returning True only if official access is
        genuinely confirmed (an installed edge package, a real API key
        env var, etc) -- see bonbon_sarvam_adapter.sarvam_capability_detector
        for the real Sarvam implementation. Never default this to a
        function that returns True; an unconfigured gated provider must
        fail closed."""
        self._max_storage_mb = max_storage_mb
        self._access_checkers = access_checkers or {}

    def check(self, entry: ModelEntry, *, explicit_approval: bool = False) -> LicenseDecision:
        if entry.download_type == "unavailable":
            return LicenseDecision(entry.model_id, False, "download_type is 'unavailable' -- no known source exists")

        if entry.provider.lower() in _GATED_PROVIDERS:
            checker = self._access_checkers.get(entry.provider.lower())
            if checker is None:
                return LicenseDecision(
                    entry.model_id, False,
                    f"provider {entry.provider!r} requires an official-access check that was never configured -- failing closed, not open",
                )
            if not checker():
                return LicenseDecision(
                    entry.model_id, False,
                    f"provider {entry.provider!r} has no confirmed official access in this environment",
                )

        if entry.commercial_allowed == "false" and not explicit_approval:
            return LicenseDecision(entry.model_id, False, "license does not permit commercial use, and no explicit approval was given")

        if entry.commercial_allowed == "unknown" and not explicit_approval:
            return LicenseDecision(
                entry.model_id, False,
                "license status is unknown -- rule 2 requires checking the license before download; unknown blocks auto-download until a human verifies it (or grants explicit_approval)",
            )

        if entry.expected_storage_mb > self._max_storage_mb and not explicit_approval:
            return LicenseDecision(
                entry.model_id, False,
                f"expected download is {entry.expected_storage_mb}MB, exceeding the {self._max_storage_mb}MB auto-download ceiling",
            )

        if not entry.enabled_by_default and not explicit_approval:
            return LicenseDecision(
                entry.model_id, False,
                "model is not enabled_by_default in the registry -- benchmark-only/candidate models require explicit approval (rule: 'do not download llama3.2:1b or qwen2.5:1.5b without explicit approval')",
            )

        return LicenseDecision(entry.model_id, True, "license permits commercial use, access confirmed where required, and storage is within the auto-download ceiling")

    def check_many(self, entries: list[ModelEntry], *, explicit_approval: bool = False) -> list[LicenseDecision]:
        return [self.check(e, explicit_approval=explicit_approval) for e in entries]
