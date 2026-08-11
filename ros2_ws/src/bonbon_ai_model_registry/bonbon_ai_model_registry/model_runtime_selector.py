"""ModelRuntimeSelector — the availability-checking side of model
selection. Answers "is this specific registry entry actually usable on
this machine right now" honestly (real importlib/subprocess/env checks,
never a guess), then hands the results to FallbackPolicy to pick the
active model per capability.

Delegates vision hardware detection to the existing
bonbon_ai_runtime.hailo_device_detector when that package is importable,
rather than re-implementing Hailo detection here -- this module is the
NEW cross-capability layer, not a replacement for the vision-specific
runtime selector that already exists and is already tested.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import time
from dataclasses import dataclass, field
from typing import Callable

from bonbon_ai_model_registry.model_fallback_policy import FallbackDecision, FallbackPolicy
from bonbon_ai_model_registry.model_registry import ModelEntry, ModelRegistry

AvailabilityChecker = Callable[[ModelEntry], bool]


def _check_pip_available(entry: ModelEntry) -> bool:
    if not entry.import_name:
        return False
    return importlib.util.find_spec(entry.import_name) is not None


def _check_ollama_available(entry: ModelEntry) -> bool:
    """Real check: is the `ollama` binary on PATH at all. Does NOT claim
    the specific model is pulled -- that requires an actual API call
    (`GET /api/tags`), which model_health_monitor.py does periodically;
    a plain availability check here stays synchronous and side-effect-free."""
    return shutil.which("ollama") is not None


def _check_hailo_available(entry: ModelEntry) -> bool:
    try:
        from bonbon_ai_runtime.hailo_device_detector import HailoDeviceDetector  # type: ignore[import-not-found]
    except ImportError:
        return False
    try:
        # .usable means BOTH the Hailo device is present on the PCIe bus
        # AND the hailort Python runtime is importable -- either alone is
        # not enough to actually run a compiled model.
        return bool(HailoDeviceDetector().detect().usable)
    except Exception:  # noqa: BLE001 -- a broken hailort install must report unavailable, not crash the selector
        return False


def _check_mock_available(_entry: ModelEntry) -> bool:
    return True


def _check_external_api_available(entry: ModelEntry) -> bool:
    """Generic fallback for hardware_target="external_api" entries with
    no bespoke checker registered: looks for an API-key-shaped env var
    named f"{PROVIDER}_API_KEY". Real Sarvam detection is more nuanced
    (edge package vs API vs neither) -- see bonbon_sarvam_adapter, which
    should be passed in as a bespoke checker for sarvam_* model_ids
    rather than relying on this generic fallback."""
    env_var = f"{entry.provider.upper()}_API_KEY"
    return bool(os.environ.get(env_var))


_DEFAULT_CHECKERS_BY_DOWNLOAD_TYPE: dict[str, AvailabilityChecker] = {
    "pip": _check_pip_available,
    "ollama": _check_ollama_available,
}

_DEFAULT_CHECKERS_BY_HARDWARE_TARGET: dict[str, AvailabilityChecker] = {
    "hailo_8": _check_hailo_available,
    "hailo_10h": _check_hailo_available,
    "mock": _check_mock_available,
    "external_api": _check_external_api_available,
}


@dataclass
class RuntimeStatus:
    capability: str
    decision: FallbackDecision
    checked_at: float
    availability: dict[str, bool] = field(default_factory=dict)


class ModelRuntimeSelector:
    def __init__(
        self,
        registry: ModelRegistry,
        *,
        bespoke_checkers: dict[str, AvailabilityChecker] | None = None,
    ) -> None:
        """`bespoke_checkers` maps model_id -> checker, taking priority
        over the generic per-download-type/hardware-target checkers below
        -- this is how bonbon_sarvam_adapter and any future capability
        with a genuinely bespoke availability signal plug in without this
        module needing to know about them by name."""
        self._registry = registry
        self._policy = FallbackPolicy(registry)
        self._bespoke = bespoke_checkers or {}

    def is_available(self, entry: ModelEntry) -> bool:
        if entry.model_id in self._bespoke:
            try:
                return bool(self._bespoke[entry.model_id](entry))
            except Exception:  # noqa: BLE001 -- a bespoke checker raising must report unavailable, never crash the caller
                return False
        checker = (
            _DEFAULT_CHECKERS_BY_HARDWARE_TARGET.get(entry.hardware_target)
            or _DEFAULT_CHECKERS_BY_DOWNLOAD_TYPE.get(entry.download_type)
        )
        if checker is None:
            # No generic or bespoke checker exists for this entry -- fail
            # closed (rule 1: never fake availability) rather than assume
            # available just because nothing said otherwise.
            return False
        try:
            return bool(checker(entry))
        except Exception:  # noqa: BLE001
            return False

    def select(self, capability: str, *, preferred_model_id: str | None = None) -> RuntimeStatus:
        # Availability is computed over the WHOLE registry, not just this
        # capability's own entries (18-point edge-AI verification, check
        # 1/4 follow-up): a fallback_model_id chain can legitimately cross
        # capability boundaries (e.g. person_detection's Hailo entry falls
        # back to object_detection's vision_mock; pose_estimation's Hailo
        # entry falls back to gesture_recognition's gesture_mediapipe_holistic)
        # -- FallbackPolicy.resolve() walks that cross-capability chain
        # correctly, but a capability-scoped availability dict silently
        # reported every cross-capability fallback target as unavailable
        # (dict lookup miss -> default False), making the ENTIRE fallback
        # chain appear exhausted even when a real, working fallback target
        # was genuinely available. Every is_available() call is still the
        # same real check as before -- this only widens which entries get
        # checked, never fabricates a result.
        availability = {e.model_id: self.is_available(e) for e in self._registry.all()}
        decision = self._policy.resolve(capability, availability, preferred_model_id=preferred_model_id)
        return RuntimeStatus(capability=capability, decision=decision, checked_at=time.time(), availability=availability)

    def select_all(self) -> dict[str, RuntimeStatus]:
        from bonbon_ai_model_registry.model_registry import CAPABILITIES

        return {cap: self.select(cap) for cap in CAPABILITIES if self._registry.by_capability(cap)}
