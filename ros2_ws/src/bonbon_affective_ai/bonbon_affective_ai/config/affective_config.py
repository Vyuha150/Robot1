"""Dataclass-based configuration for bonbon_affective_ai, loadable from ROS2 parameters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AffectiveConfig:
    """Complete configuration for the affective AI module.

    All parameters can be loaded from ROS2 node parameters via
    ``AffectiveConfig.from_node(node)``.
    """

    # ── Face analysis ────────────────────────────────────────────────────────
    face_backend: str = "deepface"
    """Backend to use for face emotion analysis: 'deepface' or 'mock'."""

    face_sample_interval_sec: float = 0.5
    """Minimum seconds between face analyses for the same tracking ID."""

    face_confidence_threshold: float = 0.55
    """Minimum dominant-emotion confidence to consider a result non-ambiguous."""

    face_temporal_window: int = 5
    """Number of recent frames used for temporal smoothing."""

    face_enabled: bool = True
    """Whether face emotion analysis is enabled."""

    # ── Voice analysis ───────────────────────────────────────────────────────
    voice_backend: str = "speechbrain"
    """Backend to use for voice emotion analysis: 'speechbrain' or 'mock'."""

    voice_confidence_threshold: float = 0.5
    """Minimum confidence to trust a voice emotion result."""

    voice_enabled: bool = True
    """Whether voice emotion analysis is enabled."""

    voice_segment_min_sec: float = 0.5
    """Minimum audio segment length (seconds) before running voice analysis."""

    # ── Text analysis ────────────────────────────────────────────────────────
    text_backend: str = "rules"
    """Backend for text emotion: 'rules', 'transformer', or 'mock'."""

    text_confidence_threshold: float = 0.5
    """Minimum confidence to trust a text emotion result."""

    text_enabled: bool = True
    """Whether text emotion analysis is enabled."""

    # ── Fusion ───────────────────────────────────────────────────────────────
    fusion_face_weight: float = 0.4
    """Relative weight of face evidence in fusion."""

    fusion_voice_weight: float = 0.35
    """Relative weight of voice evidence in fusion."""

    fusion_text_weight: float = 0.15
    """Relative weight of text evidence in fusion."""

    fusion_gesture_weight: float = 0.10
    """Relative weight of gesture evidence in fusion."""

    fusion_update_hz: float = 2.0
    """Rate at which the fusion engine publishes HumanEmotionState."""

    state_stability_window: int = 3
    """Number of consecutive fused estimates required for a state to be 'stable'."""

    # ── Privacy ──────────────────────────────────────────────────────────────
    privacy_mode: bool = False
    """Master privacy toggle."""

    privacy_level: str = "none"
    """Privacy suppression level: 'none', 'face_only', or 'suppressed'."""

    # ── Performance ──────────────────────────────────────────────────────────
    max_faces: int = 5
    """Maximum number of faces to analyse per frame."""

    processing_timeout_sec: float = 1.0
    """Wall-clock timeout for backend inference calls."""

    # ── Internal helpers ─────────────────────────────────────────────────────

    @classmethod
    def from_node(cls, node: Any) -> "AffectiveConfig":
        """Declare and read all parameters from a ROS2 node.

        Args:
            node: A ``rclpy.node.Node`` instance whose parameters will be
                declared and read.

        Returns:
            AffectiveConfig: Populated configuration dataclass.
        """
        defaults = cls()
        param_defs: list[tuple[str, Any]] = [
            ("face_backend", defaults.face_backend),
            ("face_sample_interval_sec", defaults.face_sample_interval_sec),
            ("face_confidence_threshold", defaults.face_confidence_threshold),
            ("face_temporal_window", defaults.face_temporal_window),
            ("face_enabled", defaults.face_enabled),
            ("voice_backend", defaults.voice_backend),
            ("voice_confidence_threshold", defaults.voice_confidence_threshold),
            ("voice_enabled", defaults.voice_enabled),
            ("voice_segment_min_sec", defaults.voice_segment_min_sec),
            ("text_backend", defaults.text_backend),
            ("text_confidence_threshold", defaults.text_confidence_threshold),
            ("text_enabled", defaults.text_enabled),
            ("fusion_face_weight", defaults.fusion_face_weight),
            ("fusion_voice_weight", defaults.fusion_voice_weight),
            ("fusion_text_weight", defaults.fusion_text_weight),
            ("fusion_gesture_weight", defaults.fusion_gesture_weight),
            ("fusion_update_hz", defaults.fusion_update_hz),
            ("state_stability_window", defaults.state_stability_window),
            ("privacy_mode", defaults.privacy_mode),
            ("privacy_level", defaults.privacy_level),
            ("max_faces", defaults.max_faces),
            ("processing_timeout_sec", defaults.processing_timeout_sec),
        ]

        for name, default in param_defs:
            try:
                node.declare_parameter(name, default)
            except Exception:
                pass  # already declared

        def _get(name: str) -> Any:
            return node.get_parameter(name).value

        return cls(
            face_backend=_get("face_backend"),
            face_sample_interval_sec=float(_get("face_sample_interval_sec")),
            face_confidence_threshold=float(_get("face_confidence_threshold")),
            face_temporal_window=int(_get("face_temporal_window")),
            face_enabled=bool(_get("face_enabled")),
            voice_backend=_get("voice_backend"),
            voice_confidence_threshold=float(_get("voice_confidence_threshold")),
            voice_enabled=bool(_get("voice_enabled")),
            voice_segment_min_sec=float(_get("voice_segment_min_sec")),
            text_backend=_get("text_backend"),
            text_confidence_threshold=float(_get("text_confidence_threshold")),
            text_enabled=bool(_get("text_enabled")),
            fusion_face_weight=float(_get("fusion_face_weight")),
            fusion_voice_weight=float(_get("fusion_voice_weight")),
            fusion_text_weight=float(_get("fusion_text_weight")),
            fusion_gesture_weight=float(_get("fusion_gesture_weight")),
            fusion_update_hz=float(_get("fusion_update_hz")),
            state_stability_window=int(_get("state_stability_window")),
            privacy_mode=bool(_get("privacy_mode")),
            privacy_level=_get("privacy_level"),
            max_faces=int(_get("max_faces")),
            processing_timeout_sec=float(_get("processing_timeout_sec")),
        )
