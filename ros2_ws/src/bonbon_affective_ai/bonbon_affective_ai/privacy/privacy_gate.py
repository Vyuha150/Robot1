"""Privacy gate controlling what emotion data may be processed or published."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config.affective_config import AffectiveConfig

_VALID_LEVELS: frozenset[str] = frozenset({"none", "face_only", "suppressed"})


class PrivacyGate:
    """Controls whether emotion analysis data is allowed to flow.

    Three levels are supported:

    - ``none``: All analysis is permitted (default).
    - ``face_only``: Face crops are not analysed; voice and text are allowed.
    - ``suppressed``: All analysis is suppressed; only structural metadata
      (tracking IDs, counts) may pass through.

    The gate can be updated at runtime via ``set_level`` to support the
    ``/bonbon/affective/set_privacy_mode`` service.
    """

    def __init__(self, config: "AffectiveConfig") -> None:
        """Initialise the gate from configuration.

        Args:
            config: The active ``AffectiveConfig`` instance.
        """
        self._mode: bool = config.privacy_mode
        self._level: str = config.privacy_level

    # ── Query helpers ─────────────────────────────────────────────────────────

    def should_suppress_face(self) -> bool:
        """Return True if face emotion analysis must be skipped.

        Returns:
            bool: True when level is 'face_only' or 'suppressed'.
        """
        return self._level in ("face_only", "suppressed")

    def should_suppress_voice(self) -> bool:
        """Return True if voice emotion analysis must be skipped.

        Returns:
            bool: True when level is 'suppressed'.
        """
        return self._level == "suppressed"

    def should_suppress_text(self) -> bool:
        """Return True if text emotion analysis must be skipped.

        Returns:
            bool: True when level is 'suppressed'.
        """
        return self._level == "suppressed"

    def should_suppress_all(self) -> bool:
        """Return True if all emotion analysis must be suppressed.

        Returns:
            bool: True when level is 'suppressed'.
        """
        return self._level == "suppressed"

    # ── Mutation ──────────────────────────────────────────────────────────────

    def set_level(self, level: str) -> None:
        """Update the privacy level at runtime.

        Args:
            level: New privacy level.  Must be one of 'none', 'face_only', or
                'suppressed'.

        Raises:
            ValueError: If ``level`` is not a recognised value.
        """
        if level not in _VALID_LEVELS:
            raise ValueError(
                f"Invalid privacy level '{level}'.  "
                f"Must be one of: {sorted(_VALID_LEVELS)}"
            )
        self._level = level

    def set_mode(self, enabled: bool, level: str) -> None:
        """Set both the mode toggle and the level simultaneously.

        Args:
            enabled: Whether privacy mode is active.
            level: New privacy level string.
        """
        self._mode = enabled
        self.set_level(level)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def current_level(self) -> str:
        """Return the current privacy level string."""
        return self._level

    @property
    def is_privacy_mode_active(self) -> bool:
        """Return True if the privacy mode flag is set."""
        return self._mode
