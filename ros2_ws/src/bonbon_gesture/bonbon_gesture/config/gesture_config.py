"""
bonbon_gesture.config.gesture_config
=====================================
Central configuration dataclass for the gesture recognition pipeline.
All parameters can be overridden via ROS2 parameters (gesture.yaml).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GestureConfig:
    """Runtime configuration for the GestureNode and all sub-components.

    Attributes:
        backend: Which processing backend to use. 'mediapipe' requires the
            mediapipe Python package; falls back to 'mock' if unavailable.
        enabled: Master enable/disable switch for gesture processing.
        confidence_threshold: Minimum confidence required to publish a
            GestureEvent (0.0–1.0).
        temporal_window: Number of frames used by the majority-vote smoother.
        gesture_cooldown_sec: Minimum seconds between repeated events for the
            same gesture+person combination. Safety gestures bypass this.
        max_persons: Maximum number of simultaneous persons tracked.
        frame_sample_rate: Process every Nth incoming camera frame to stay
            within the CPU budget.
        head_gesture_enabled: Enable head-nod/shake classification.
        hand_gesture_enabled: Enable hand gesture classification.
        body_gesture_enabled: Enable body/arm pose classification.
        safety_gesture_immediate: When True safety-relevant gestures bypass
            both temporal smoothing cooldown and frame skipping.
        processing_timeout_sec: Hard wall-clock budget for one backend call.
            Frame is discarded if the call exceeds this duration.
        min_visibility_threshold: MediaPipe landmark visibility score minimum.
            Landmarks below this are treated as absent.
    """

    backend: str = "mediapipe"
    enabled: bool = True
    confidence_threshold: float = 0.65
    temporal_window: int = 4
    gesture_cooldown_sec: float = 1.0
    max_persons: int = 5
    frame_sample_rate: int = 3
    head_gesture_enabled: bool = True
    hand_gesture_enabled: bool = True
    body_gesture_enabled: bool = True
    safety_gesture_immediate: bool = True
    processing_timeout_sec: float = 0.08
    min_visibility_threshold: float = 0.5

    @classmethod
    def from_ros_params(cls, node: "rclpy.node.Node") -> "GestureConfig":  # type: ignore[name-defined]
        """Construct a GestureConfig by reading ROS2 parameters from *node*.

        Only parameters that have been declared on the node will be read.
        Parameters not yet declared retain their default values.

        Args:
            node: A live rclpy Node (or LifecycleNode) instance.

        Returns:
            A fully populated GestureConfig.
        """
        def _get(name: str, default):  # type: ignore[no-untyped-def]
            try:
                return node.get_parameter(name).value
            except Exception:  # parameter not declared
                return default

        defaults = cls()
        return cls(
            backend=_get("backend", defaults.backend),
            enabled=_get("enabled", defaults.enabled),
            confidence_threshold=_get("confidence_threshold", defaults.confidence_threshold),
            temporal_window=int(_get("temporal_window", defaults.temporal_window)),
            gesture_cooldown_sec=float(_get("gesture_cooldown_sec", defaults.gesture_cooldown_sec)),
            max_persons=int(_get("max_persons", defaults.max_persons)),
            frame_sample_rate=int(_get("frame_sample_rate", defaults.frame_sample_rate)),
            head_gesture_enabled=_get("head_gesture_enabled", defaults.head_gesture_enabled),
            hand_gesture_enabled=_get("hand_gesture_enabled", defaults.hand_gesture_enabled),
            body_gesture_enabled=_get("body_gesture_enabled", defaults.body_gesture_enabled),
            safety_gesture_immediate=_get("safety_gesture_immediate", defaults.safety_gesture_immediate),
            processing_timeout_sec=float(_get("processing_timeout_sec", defaults.processing_timeout_sec)),
            min_visibility_threshold=float(_get("min_visibility_threshold", defaults.min_visibility_threshold)),
        )
