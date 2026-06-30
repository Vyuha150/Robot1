"""Tests for DataFeedbackNode's non-blocking automatic write path.

Exercises the REAL _cb_gesture_event / _write_gesture_failure_case methods
(not a re-implementation) to verify the fix for check #13 ("database writes
are batched and non-blocking"): the gesture-event callback must never
block on the SQLite write itself -- it only admits to a BoundedInferenceQueue
and submits to a ThreadPoolExecutor.

ROS2 is stubbed at import time so these tests run under plain pytest,
following the same pattern established in bonbon_llm/tests/test_llm_orchestrator.py.
"""

from __future__ import annotations

import sys
import time
import types
from unittest.mock import MagicMock


def _stub_ros():
    fake_rclpy = types.ModuleType("rclpy")
    fake_rclpy.init = MagicMock()
    fake_rclpy.shutdown = MagicMock()
    fake_rclpy.spin = MagicMock()

    class FakeLifecycleNode:
        def __init__(self, *a, **kw):
            pass

        def get_logger(self):
            return MagicMock()

        def declare_parameter(self, *a, **kw):
            return MagicMock()

        def get_parameter(self, *a, **kw):
            return MagicMock(value="test_value")

        def create_subscription(self, *a, **kw):
            return MagicMock()

        def create_lifecycle_publisher(self, *a, **kw):
            return MagicMock()

        def create_service(self, *a, **kw):
            return MagicMock()

        def create_timer(self, *a, **kw):
            return MagicMock()

        def destroy_subscription(self, *a, **kw):
            pass

        def destroy_publisher(self, *a, **kw):
            pass

        def destroy_service(self, *a, **kw):
            pass

        def destroy_node(self):
            pass

    lifecycle_mod = types.ModuleType("rclpy.lifecycle")
    lifecycle_mod.LifecycleNode = FakeLifecycleNode
    lifecycle_mod.State = MagicMock
    lifecycle_mod.TransitionCallbackReturn = MagicMock(SUCCESS="SUCCESS", FAILURE="FAILURE")

    qos_mod = types.ModuleType("rclpy.qos")
    for cls_name in ("QoSProfile", "DurabilityPolicy", "HistoryPolicy", "ReliabilityPolicy"):
        setattr(qos_mod, cls_name, MagicMock())

    for name, mod in [
        ("rclpy", fake_rclpy),
        ("rclpy.lifecycle", lifecycle_mod),
        ("rclpy.qos", qos_mod),
        ("lifecycle_msgs", types.ModuleType("lifecycle_msgs")),
        ("lifecycle_msgs.msg", types.ModuleType("lifecycle_msgs.msg")),
        ("bonbon_msgs", types.ModuleType("bonbon_msgs")),
        ("bonbon_msgs.msg", types.ModuleType("bonbon_msgs.msg")),
        ("bonbon_srvs", types.ModuleType("bonbon_srvs")),
        ("bonbon_srvs.srv", types.ModuleType("bonbon_srvs.srv")),
    ]:
        sys.modules.setdefault(name, mod)

    for attr in ("GestureEvent", "ModuleHealth", "PerceptionPolicy"):
        setattr(sys.modules["bonbon_msgs.msg"], attr, MagicMock)
    for attr in ("HealthCheck", "ReportFailureCase"):
        setattr(sys.modules["bonbon_srvs.srv"], attr, MagicMock)
    sys.modules["lifecycle_msgs.msg"].State = MagicMock


_stub_ros()

from bonbon_data_feedback.nodes.data_feedback_node import DataFeedbackNode  # noqa: E402


def _make_intent_gesture(gesture_type="point", confidence=0.4, person_track_id="ptrk_1"):
    msg = MagicMock()
    msg.gesture_type = gesture_type
    msg.confidence = confidence
    msg.person_track_id = person_track_id
    msg.hand_side = "right"
    msg.body_part = "hand"
    return msg


def _wait_for(predicate, timeout_sec=2.0):
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class TestNonBlockingAutomaticWritePath:
    def _make_node(self, executor=True):
        from concurrent.futures import ThreadPoolExecutor

        from bonbon_perception_efficiency.core.bounded_inference_queue import (
            BoundedInferenceQueue,
        )

        node = DataFeedbackNode("test_data_feedback")
        node._failure_logger = MagicMock()
        node._gesture_log_queue = BoundedInferenceQueue(max_depth=2)
        node._write_executor = ThreadPoolExecutor(max_workers=1) if executor else None
        node._gesture_floor = 0.65
        return node

    def test_callback_returns_immediately_without_calling_logger_synchronously(self):
        """The defining property of the fix: _cb_gesture_event must NOT call
        the (slow, blocking) logger itself -- only dispatch to the executor."""
        node = self._make_node()
        node._failure_logger.log = MagicMock(side_effect=lambda **kw: time.sleep(0.5))

        start = time.perf_counter()
        node._cb_gesture_event(_make_intent_gesture(confidence=0.2))
        elapsed = time.perf_counter() - start

        assert elapsed < 0.1, "the callback blocked on the slow write instead of dispatching it"
        assert _wait_for(lambda: node._failure_logger.log.call_count == 1)

    def test_confident_gesture_is_not_logged_at_all(self):
        node = self._make_node()
        node._cb_gesture_event(_make_intent_gesture(confidence=0.9))
        time.sleep(0.05)
        node._failure_logger.log.assert_not_called()

    def test_low_confidence_gesture_is_logged_via_executor(self):
        node = self._make_node()
        node._cb_gesture_event(_make_intent_gesture(confidence=0.1, gesture_type="wave"))
        assert _wait_for(lambda: node._failure_logger.log.call_count == 1)
        _, kwargs = node._failure_logger.log.call_args
        assert kwargs["category"] == "gesture"
        assert kwargs["actual_label"] == "wave"

    def test_queue_releases_slot_after_write_completes(self):
        node = self._make_node()
        node._cb_gesture_event(_make_intent_gesture(confidence=0.1))
        assert _wait_for(lambda: node._gesture_log_queue.depth == 0)

    def test_backpressure_drops_when_queue_full(self):
        """A burst of low-confidence events larger than max_depth must not
        block -- excess events are dropped, not queued without bound."""
        node = self._make_node()
        node._failure_logger.log = MagicMock(side_effect=lambda **kw: time.sleep(0.3))

        for _ in range(10):
            node._cb_gesture_event(_make_intent_gesture(confidence=0.1))

        assert node._gesture_log_queue.dropped_count > 0

    def test_no_executor_configured_is_a_safe_noop(self):
        node = self._make_node(executor=False)
        node._cb_gesture_event(_make_intent_gesture(confidence=0.1))  # must not raise
        node._failure_logger.log.assert_not_called()

    def test_write_failure_still_releases_the_queue_slot(self):
        """A DB error in the worker thread must not leak a queue slot --
        otherwise repeated failures would permanently shrink capacity."""
        node = self._make_node()
        node._failure_logger.log = MagicMock(side_effect=RuntimeError("disk full"))

        node._cb_gesture_event(_make_intent_gesture(confidence=0.1))
        assert _wait_for(lambda: node._gesture_log_queue.depth == 0)
        assert node._error_count == 1
