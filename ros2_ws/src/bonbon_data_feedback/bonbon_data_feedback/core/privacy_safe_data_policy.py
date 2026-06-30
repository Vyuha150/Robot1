"""PrivacySafeDataPolicy — the single gate every other component in this
package must consult before persisting anything.

Hard rule from the project brief: raw face/audio is NEVER stored by default.
Raw snapshot storage is only possible when debug_mode is explicitly enabled
(an explicit constructor/config flag — never inferred, never defaulted on).
Even in debug mode, this policy strips any field whose KEY looks like it
might carry raw biometric payload, as a second line of defense against a
caller accidentally passing raw bytes in a "safe" context dict.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Keys that must never appear in a stored context dict, even in debug mode —
# these route through raw_snapshot_path instead (a file reference, not the
# payload itself, see FailureCaseLogger).
_FORBIDDEN_CONTEXT_KEYS = frozenset(
    {
        "face_embedding",
        "face_image",
        "audio_bytes",
        "audio_samples",
        "raw_image",
        "raw_audio",
        "image_bytes",
        "voice_embedding",
        "biometric_template",
    }
)

_DEFAULT_RETENTION_DAYS = {
    "object": 90,
    "gesture": 90,
    "speaker": 60,  # voice-adjacent data — shorter retention
    "face": 30,  # most sensitive category — shortest retention
    "emotion": 60,
    "default": 90,
}


@dataclass
class SanitizeResult:
    sanitized: dict
    stripped_keys: list[str] = field(default_factory=list)


class PrivacySafeDataPolicy:
    def __init__(
        self,
        debug_mode_enabled: bool = False,
        retention_days_by_category: dict[str, int] | None = None,
    ) -> None:
        self._debug_mode = debug_mode_enabled
        self._retention = dict(_DEFAULT_RETENTION_DAYS)
        if retention_days_by_category:
            self._retention.update(retention_days_by_category)

    @property
    def debug_mode_enabled(self) -> bool:
        return self._debug_mode

    def is_raw_snapshot_allowed(self) -> bool:
        """Raw face/audio snapshots may ONLY be stored when this is True —
        and this is only True when debug_mode_enabled was explicitly set."""
        return self._debug_mode

    def sanitize_context(self, context: dict) -> SanitizeResult:
        """Strips any forbidden key, regardless of debug mode — debug mode
        controls whether a SEPARATE raw_snapshot_path may be set, never
        whether raw payload can ride along in the general context dict."""
        stripped = []
        clean = {}
        for k, v in context.items():
            if k.lower() in _FORBIDDEN_CONTEXT_KEYS:
                stripped.append(k)
                continue
            clean[k] = v
        return SanitizeResult(sanitized=clean, stripped_keys=stripped)

    def retention_days_for(self, category: str) -> int:
        return self._retention.get(category, self._retention["default"])

    def is_expired(self, category: str, created_at: float, now: float) -> bool:
        retention_sec = self.retention_days_for(category) * 86400.0
        return (now - created_at) > retention_sec
