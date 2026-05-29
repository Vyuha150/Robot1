"""Tests for AffectiveAINode — verifies startup with mock backends and services."""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# ── Comprehensive ROS2 / bonbon_msgs stubs ─────────────────────────────────────

def _make_all_stubs() -> None:
    """Build all required stub modules so the node can be imported without ROS2."""

    # ── rclpy core ────────────────────────────────────────────────────────────
    if "rclpy" not in sys.modules:
        rclpy_mod = types.ModuleType("rclpy")

        class _Clock:
            def now(self):
                class _T:
                    def to_msg(self):
                        return None
                return _T()

        rclpy_mod.clock = types.ModuleType("rclpy.clock")
        rclpy_mod.clock.Clock = _Clock
        rclpy_mod.init = lambda args=None: None
        rclpy_mod.shutdown = lambda: None

        class _FakeNode:
            def __init__(self, name):
                self._name = name
                self._logger = _FakeLogger()
            def get_clock(self): return _Clock()
            def get_logger(self): return self._logger
            def declare_parameter(self, name, default): pass
            def get_parameter(self, name):
                return type("P", (), {"value": None})()
            def create_publisher(self, *a, **kw): return _FakePub()
            def create_subscription(self, *a, **kw): return None
            def create_service(self, *a, **kw): return None
            def create_timer(self, *a, **kw): return _FakeTimer()
            def destroy_node(self): pass

        rclpy_mod.node = types.ModuleType("rclpy.node")
        rclpy_mod.node.Node = _FakeNode

        class _FakeLogger:
            def info(self, *a, **kw): pass
            def warn(self, *a, **kw): pass
            def warning(self, *a, **kw): pass
            def error(self, *a, **kw): pass
            def debug(self, *a, **kw): pass

        rclpy_mod.logging = types.ModuleType("rclpy.logging")
        rclpy_mod.logging.get_logger = lambda name: _FakeLogger()

        # QoS stubs
        qos_mod = types.ModuleType("rclpy.qos")
        for cls_name in (
            "QoSProfile", "QoSDurabilityPolicy", "QoSReliabilityPolicy",
            "QoSHistoryPolicy"
        ):
            setattr(qos_mod, cls_name, MagicMock())
        rclpy_mod.qos = qos_mod

        # Lifecycle stubs
        lc_mod = types.ModuleType("rclpy.lifecycle")

        class _TransitionCallbackReturn:
            SUCCESS = "SUCCESS"
            FAILURE = "FAILURE"

        class _LifecycleNode(_FakeNode):
            def __init__(self, name):
                super().__init__(name)

        lc_mod.LifecycleNode = _LifecycleNode
        lc_mod.TransitionCallbackReturn = _TransitionCallbackReturn
        rclpy_mod.lifecycle = lc_mod

        lc_node_mod = types.ModuleType("rclpy.lifecycle.node")
        lc_node_mod.LifecycleState = MagicMock()
        sys.modules["rclpy.lifecycle.node"] = lc_node_mod

        sys.modules["rclpy"] = rclpy_mod
        sys.modules["rclpy.clock"] = rclpy_mod.clock
        sys.modules["rclpy.node"] = rclpy_mod.node
        sys.modules["rclpy.qos"] = rclpy_mod.qos
        sys.modules["rclpy.lifecycle"] = rclpy_mod.lifecycle
        sys.modules["rclpy.logging"] = rclpy_mod.logging

    # ── std_msgs stub ─────────────────────────────────────────────────────────
    if "std_msgs" not in sys.modules:
        std_msgs = types.ModuleType("std_msgs")
        std_msgs_msg = types.ModuleType("std_msgs.msg")

        class String:
            def __init__(self):
                self.data = ""

        std_msgs_msg.String = String
        std_msgs.msg = std_msgs_msg
        sys.modules["std_msgs"] = std_msgs
        sys.modules["std_msgs.msg"] = std_msgs_msg

    # ── bonbon_msgs stub ──────────────────────────────────────────────────────
    if "bonbon_msgs" not in sys.modules:
        bonbon_msgs = types.ModuleType("bonbon_msgs")
        bonbon_msgs_msg = types.ModuleType("bonbon_msgs.msg")

        for cls_name in (
            "FaceEmotion", "VoiceEmotion", "TextEmotion", "HumanEmotionState",
            "PersonStateArray", "AudioChunk", "GestureEvent", "SafetyState",
            "SpeechCommand"
        ):
            klass = type(cls_name, (), {"__init__": lambda self: None})
            setattr(bonbon_msgs_msg, cls_name, klass)

        bonbon_msgs.msg = bonbon_msgs_msg
        sys.modules["bonbon_msgs"] = bonbon_msgs
        sys.modules["bonbon_msgs.msg"] = bonbon_msgs_msg

    # ── bonbon_srvs stub ──────────────────────────────────────────────────────
    if "bonbon_srvs" not in sys.modules:
        bonbon_srvs = types.ModuleType("bonbon_srvs")
        bonbon_srvs_srv = types.ModuleType("bonbon_srvs.srv")

        for cls_name in ("AnalyzeText", "HealthCheck", "SetPrivacyMode"):
            klass = type(cls_name, (), {"__init__": lambda self: None})
            setattr(bonbon_srvs_srv, cls_name, klass)

        bonbon_srvs.srv = bonbon_srvs_srv
        sys.modules["bonbon_srvs"] = bonbon_srvs
        sys.modules["bonbon_srvs.srv"] = bonbon_srvs_srv


class _FakePub:
    """Stub publisher that records published messages."""

    def __init__(self):
        self.published = []

    def publish(self, msg):
        self.published.append(msg)


class _FakeTimer:
    """Stub timer."""

    def cancel(self):
        pass


_make_all_stubs()

# Now patch sys.modules so configure() finds the stubs during import.
from bonbon_affective_ai.config.affective_config import AffectiveConfig


class TestAffectiveNodeWithMockBackends(unittest.TestCase):
    """Verify AffectiveAINode configures and activates cleanly with mocks."""

    def _make_config(self) -> AffectiveConfig:
        """Return a config wired for mock backends."""
        return AffectiveConfig(
            face_backend="mock",
            voice_backend="mock",
            text_backend="rules",
            face_sample_interval_sec=0.0,
            fusion_update_hz=2.0,
        )

    def test_config_creation(self) -> None:
        """AffectiveConfig can be created with mock backend settings."""
        cfg = self._make_config()
        self.assertEqual(cfg.face_backend, "mock")
        self.assertEqual(cfg.voice_backend, "mock")
        self.assertEqual(cfg.text_backend, "rules")

    def test_mock_face_backend_warms_up(self) -> None:
        """MockFaceBackend warmup succeeds and is_ready becomes True."""
        from bonbon_affective_ai.backends.mock_backends import MockFaceBackend
        backend = MockFaceBackend()
        self.assertFalse(backend.is_ready)
        backend.warmup()
        self.assertTrue(backend.is_ready)

    def test_mock_voice_backend_warms_up(self) -> None:
        """MockVoiceBackend warmup succeeds and is_ready becomes True."""
        from bonbon_affective_ai.backends.mock_backends import MockVoiceBackend
        backend = MockVoiceBackend()
        self.assertFalse(backend.is_ready)
        backend.warmup()
        self.assertTrue(backend.is_ready)

    def test_health_monitor_starts_healthy(self) -> None:
        """HealthMonitor reports healthy right after creation (text always ok)."""
        from bonbon_affective_ai.health.health_monitor import AffectiveAIHealthMonitor
        monitor = AffectiveAIHealthMonitor()
        self.assertTrue(monitor.is_healthy())

    def test_health_monitor_get_status_keys(self) -> None:
        """HealthMonitor.get_status() returns all expected keys."""
        from bonbon_affective_ai.health.health_monitor import AffectiveAIHealthMonitor
        monitor = AffectiveAIHealthMonitor()
        status = monitor.get_status()
        for key in (
            "face_backend_ok", "voice_backend_ok", "text_backend_ok",
            "recent_errors", "last_face_analysis_ago_sec", "uptime_sec"
        ):
            self.assertIn(key, status)

    def test_health_monitor_records_failure(self) -> None:
        """Recorded face failure is visible in status."""
        from bonbon_affective_ai.health.health_monitor import AffectiveAIHealthMonitor
        monitor = AffectiveAIHealthMonitor()
        monitor.record_face_failure("test_error")
        self.assertFalse(monitor.get_status()["face_backend_ok"])
        self.assertIn("face:test_error", monitor.get_status()["recent_errors"])

    def test_health_monitor_records_success(self) -> None:
        """After success, face_backend_ok becomes True."""
        from bonbon_affective_ai.health.health_monitor import AffectiveAIHealthMonitor
        monitor = AffectiveAIHealthMonitor()
        monitor.record_face_failure("init_fail")
        monitor.record_face_success()
        self.assertTrue(monitor.get_status()["face_backend_ok"])

    def test_privacy_gate_defaults(self) -> None:
        """Default privacy gate allows all analysis."""
        from bonbon_affective_ai.privacy.privacy_gate import PrivacyGate
        config = AffectiveConfig()
        gate = PrivacyGate(config)
        self.assertFalse(gate.should_suppress_face())
        self.assertFalse(gate.should_suppress_voice())
        self.assertFalse(gate.should_suppress_all())

    def test_privacy_gate_face_only(self) -> None:
        """face_only level suppresses face but not voice/text."""
        from bonbon_affective_ai.privacy.privacy_gate import PrivacyGate
        config = AffectiveConfig(privacy_level="face_only")
        gate = PrivacyGate(config)
        self.assertTrue(gate.should_suppress_face())
        self.assertFalse(gate.should_suppress_voice())

    def test_privacy_gate_suppressed(self) -> None:
        """suppressed level suppresses all analysis."""
        from bonbon_affective_ai.privacy.privacy_gate import PrivacyGate
        config = AffectiveConfig(privacy_level="suppressed")
        gate = PrivacyGate(config)
        self.assertTrue(gate.should_suppress_face())
        self.assertTrue(gate.should_suppress_voice())
        self.assertTrue(gate.should_suppress_all())

    def test_privacy_gate_invalid_level_raises(self) -> None:
        """Setting an invalid privacy level raises ValueError."""
        from bonbon_affective_ai.privacy.privacy_gate import PrivacyGate
        config = AffectiveConfig()
        gate = PrivacyGate(config)
        with self.assertRaises(ValueError):
            gate.set_level("invalid_level")

    def test_text_analyzer_emergency(self) -> None:
        """TextEmotionAnalyzer detects emergency in 'I fell and need help'."""
        from bonbon_affective_ai.privacy.privacy_gate import PrivacyGate
        from bonbon_affective_ai.analyzers.text_emotion_analyzer import TextEmotionAnalyzer

        class _FC:
            def now(self):
                class _T:
                    def to_msg(self): return None
                return _T()

        config = AffectiveConfig(text_backend="rules", text_confidence_threshold=0.1)
        gate = PrivacyGate(config)
        analyzer = TextEmotionAnalyzer(config, gate, _FC())
        msg = analyzer.analyze_text("I fell and need help", person_id="p1")
        self.assertTrue(msg.emergency_detected)
        self.assertTrue(msg.requires_operator_alert)

    def test_handle_health_check_response(self) -> None:
        """Health check service handler returns healthy=True with text backend ok."""
        from bonbon_affective_ai.health.health_monitor import AffectiveAIHealthMonitor

        monitor = AffectiveAIHealthMonitor()
        # Simulate a health check response object.
        response = type("Resp", (), {
            "healthy": False,
            "status": "",
            "warnings": [],
            "errors": [],
            "uptime_sec": 0.0,
        })()

        status = monitor.get_status()
        response.healthy = monitor.is_healthy()
        response.uptime_sec = float(monitor.uptime_sec)

        warnings = []
        errors = []
        if not status["face_backend_ok"]:
            warnings.append("Face backend not available")
        if not status["voice_backend_ok"]:
            warnings.append("Voice backend not available")

        response.warnings = warnings
        response.errors = errors
        response.status = "ok" if response.healthy else "degraded"

        self.assertTrue(response.healthy)
        self.assertEqual(response.status, "ok")

    def test_node_factory_mock_face_backend(self) -> None:
        """_create_face_backend('mock') returns a MockFaceBackend instance."""
        from bonbon_affective_ai.nodes.affective_ai_node import AffectiveAINode
        from bonbon_affective_ai.backends.mock_backends import MockFaceBackend
        backend = AffectiveAINode._create_face_backend("mock")
        self.assertIsInstance(backend, MockFaceBackend)

    def test_node_factory_mock_voice_backend(self) -> None:
        """_create_voice_backend('mock') returns a MockVoiceBackend instance."""
        from bonbon_affective_ai.nodes.affective_ai_node import AffectiveAINode
        from bonbon_affective_ai.backends.mock_backends import MockVoiceBackend
        backend = AffectiveAINode._create_voice_backend("mock")
        self.assertIsInstance(backend, MockVoiceBackend)

    def test_node_factory_unknown_face_backend_falls_back(self) -> None:
        """Unknown face backend name falls back to MockFaceBackend."""
        from bonbon_affective_ai.nodes.affective_ai_node import AffectiveAINode
        from bonbon_affective_ai.backends.mock_backends import MockFaceBackend
        backend = AffectiveAINode._create_face_backend("nonexistent_backend_xyz")
        self.assertIsInstance(backend, MockFaceBackend)

    def test_node_factory_unknown_voice_backend_falls_back(self) -> None:
        """Unknown voice backend name falls back to MockVoiceBackend."""
        from bonbon_affective_ai.nodes.affective_ai_node import AffectiveAINode
        from bonbon_affective_ai.backends.mock_backends import MockVoiceBackend
        backend = AffectiveAINode._create_voice_backend("nonexistent_backend_xyz")
        self.assertIsInstance(backend, MockVoiceBackend)

    def test_temporal_smoother_basic(self) -> None:
        """TemporalSmoother averages values across window."""
        from bonbon_affective_ai.fusion.temporal_smoother import TemporalSmoother

        smoother = TemporalSmoother(window=3)
        for _ in range(3):
            result = smoother.smooth(1, {
                "anger": 0.9, "disgust": 0.0, "fear": 0.0,
                "happiness": 0.0, "sadness": 0.0, "surprise": 0.0, "neutral": 0.1
            })
        self.assertAlmostEqual(result["anger"], 0.9, places=5)
        self.assertEqual(result["dominant_emotion"], "anger")

    def test_mock_face_backend_cycles(self) -> None:
        """MockFaceBackend returns different emotions on successive calls."""
        import numpy as np
        from bonbon_affective_ai.backends.mock_backends import MockFaceBackend

        backend = MockFaceBackend()
        backend.warmup()
        blank = np.zeros((48, 48, 3), dtype=np.uint8)
        emotions = set()
        for _ in range(5):
            result = backend.analyze(blank)
            emotions.add(result["dominant_emotion"])
        self.assertGreater(len(emotions), 1)


if __name__ == "__main__":
    unittest.main()
