"""Shared pytest fixtures + ROS2/message stubs for bonbon_affective_ai tests.

Why this exists
---------------
The package's nodes and analyzers import ``rclpy`` and the generated
``bonbon_msgs`` / ``bonbon_srvs`` packages, which are not available in a plain
(non-ROS2) pytest environment. Each individual test file used to install its
own ``sys.modules`` stubs guarded by ``if "bonbon_msgs" not in sys.modules``.
When the whole suite runs in one process, the *first* test file imported won
that guard and its (possibly incomplete) stubs were used by every other file —
causing spurious failures (e.g. a message stub missing ``header``).

``conftest.py`` is imported by pytest *before* any test module, so installing
**one complete set of permissive stubs here** guarantees every test file sees
the same, fully-featured stubs. The per-file guards then simply skip.

The message stub is permissive: any attribute can be set, and nested
message-like attributes (``msg.header.stamp``) auto-vivify, so it tolerates
every field the analyzers and node set without enumerating them.
"""

from __future__ import annotations

import sys
import types


# ── Permissive message / request stand-in ──────────────────────────────────

class _StubMsg:
    """A permissive ROS2 message stand-in.

    * Any attribute may be assigned and read back.
    * Reading an unset attribute auto-vivifies a nested ``_StubMsg`` so that
      ``msg.header.stamp = ...`` works without predefining ``header``.
    * Constructor accepts keyword field initial values.
    """

    def __init__(self, **kwargs):
        object.__setattr__(self, "_fields", {})
        for key, value in kwargs.items():
            self._fields[key] = value

    def __getattr__(self, name):
        # Only called when normal lookup fails.
        fields = object.__getattribute__(self, "_fields")
        if name not in fields:
            fields[name] = _StubMsg()
        return fields[name]

    def __setattr__(self, name, value):
        object.__getattribute__(self, "_fields")[name] = value

    def __bool__(self):
        # An unset / auto-vivified field behaves like a zero-initialised ROS2
        # field (bool→False, so `if msg.some_unset_flag:` is False). Fields that
        # are explicitly assigned a real value return that value directly and
        # never reach here.
        return False

    def __repr__(self):  # pragma: no cover - debug aid
        return f"_StubMsg({object.__getattribute__(self, '_fields')!r})"


def _msg_class(name: str):
    """Create a named message class backed by :class:`_StubMsg`."""
    return type(name, (_StubMsg,), {})


def _install_stubs() -> None:
    """Install a complete, permissive stub surface into ``sys.modules``."""

    # ── rclpy ───────────────────────────────────────────────────────────────
    if "rclpy" not in sys.modules:
        rclpy_mod = types.ModuleType("rclpy")

        class _Stamp:
            def __init__(self):
                self.sec = 0
                self.nanosec = 0

        class _Clock:
            def now(self):
                class _Now:
                    def to_msg(self_inner):
                        return _Stamp()
                return _Now()

        class _Logger:
            def info(self, *a, **k): pass
            def warn(self, *a, **k): pass
            def warning(self, *a, **k): pass
            def error(self, *a, **k): pass
            def debug(self, *a, **k): pass

        class _Pub:
            def __init__(self):
                self.published = []
                self.is_activated = True

            def publish(self, msg):
                self.published.append(msg)

            def on_activate(self, *a, **k): pass
            def on_deactivate(self, *a, **k): pass

        class _Timer:
            def cancel(self): pass

        class _Param:
            def __init__(self, value=None):
                self._value = value
                self.value = value

            def get_parameter_value(self):
                return self

            @property
            def string_value(self):
                return self._value if isinstance(self._value, str) else ""

            @property
            def double_value(self):
                return float(self._value) if isinstance(self._value, (int, float)) else 0.0

            @property
            def integer_value(self):
                return int(self._value) if isinstance(self._value, (int, float)) else 0

            @property
            def bool_value(self):
                return bool(self._value)

        class _FakeNode:
            def __init__(self, name="node"):
                self._name = name
                self._logger = _Logger()
                self._params = {}

            def get_clock(self): return _Clock()
            def get_logger(self): return self._logger
            def declare_parameter(self, name, default=None, *a, **k):
                self._params[name] = default
                return _Param(default)
            def get_parameter(self, name):
                return _Param(self._params.get(name))
            def create_publisher(self, *a, **k): return _Pub()
            def create_lifecycle_publisher(self, *a, **k): return _Pub()
            def create_subscription(self, *a, **k): return object()
            def create_service(self, *a, **k): return object()
            def create_timer(self, *a, **k): return _Timer()
            def destroy_node(self): pass
            def destroy_publisher(self, *a, **k): pass
            def destroy_subscription(self, *a, **k): pass
            def destroy_service(self, *a, **k): pass
            def destroy_timer(self, *a, **k): pass

        class _TransitionCallbackReturn:
            SUCCESS = "SUCCESS"
            FAILURE = "FAILURE"
            ERROR = "ERROR"

        class _State:
            pass

        class _LifecycleNode(_FakeNode):
            pass

        rclpy_mod.init = lambda args=None: None
        rclpy_mod.shutdown = lambda: None
        rclpy_mod.try_shutdown = lambda: None
        rclpy_mod.spin = lambda node: None
        rclpy_mod.ok = lambda: True

        clock_mod = types.ModuleType("rclpy.clock"); clock_mod.Clock = _Clock
        node_mod = types.ModuleType("rclpy.node"); node_mod.Node = _FakeNode
        logging_mod = types.ModuleType("rclpy.logging")
        logging_mod.get_logger = lambda name="": _Logger()

        qos_mod = types.ModuleType("rclpy.qos")

        class _QoSProfile:
            def __init__(self, *a, **k): pass

        for cls in ("QoSProfile", "ReliabilityPolicy", "DurabilityPolicy",
                    "HistoryPolicy", "QoSReliabilityPolicy", "QoSDurabilityPolicy",
                    "QoSHistoryPolicy"):
            setattr(qos_mod, cls, _QoSProfile if cls == "QoSProfile"
                    else type(cls, (), {"RELIABLE": 1, "BEST_EFFORT": 2,
                                        "VOLATILE": 1, "TRANSIENT_LOCAL": 2,
                                        "KEEP_LAST": 1}))

        lc_mod = types.ModuleType("rclpy.lifecycle")
        lc_mod.LifecycleNode = _LifecycleNode
        lc_mod.Node = _LifecycleNode
        lc_mod.State = _State
        lc_mod.TransitionCallbackReturn = _TransitionCallbackReturn
        lc_pub_mod = types.ModuleType("rclpy.lifecycle.publisher")
        lc_pub_mod.LifecyclePublisher = _Pub

        rclpy_mod.clock = clock_mod
        rclpy_mod.node = node_mod
        rclpy_mod.logging = logging_mod
        rclpy_mod.qos = qos_mod
        rclpy_mod.lifecycle = lc_mod

        sys.modules["rclpy"] = rclpy_mod
        sys.modules["rclpy.clock"] = clock_mod
        sys.modules["rclpy.node"] = node_mod
        sys.modules["rclpy.logging"] = logging_mod
        sys.modules["rclpy.qos"] = qos_mod
        sys.modules["rclpy.lifecycle"] = lc_mod
        sys.modules["rclpy.lifecycle.publisher"] = lc_pub_mod

    # ── std_msgs ──────────────────────────────────────────────────────────────
    if "std_msgs" not in sys.modules:
        std = types.ModuleType("std_msgs")
        std_msg = types.ModuleType("std_msgs.msg")
        std_msg.String = _msg_class("String")
        std_msg.Bool = _msg_class("Bool")
        std_msg.Header = _msg_class("Header")
        std.msg = std_msg
        sys.modules["std_msgs"] = std
        sys.modules["std_msgs.msg"] = std_msg

    # ── builtin_interfaces ────────────────────────────────────────────────────
    if "builtin_interfaces" not in sys.modules:
        bi = types.ModuleType("builtin_interfaces")
        bi_msg = types.ModuleType("builtin_interfaces.msg")
        bi_msg.Time = _msg_class("Time")
        bi.msg = bi_msg
        sys.modules["builtin_interfaces"] = bi
        sys.modules["builtin_interfaces.msg"] = bi_msg

    # ── bonbon_msgs ───────────────────────────────────────────────────────────
    if "bonbon_msgs" not in sys.modules:
        bm = types.ModuleType("bonbon_msgs")
        bm_msg = types.ModuleType("bonbon_msgs.msg")
        for name in (
            "FaceEmotion", "VoiceEmotion", "TextEmotion", "HumanEmotionState",
            "PersonState", "PersonStateArray", "AudioChunk", "GestureEvent",
            "SafetyState", "SpeechCommand", "ModuleHealth", "RiskEvent",
            "SpatialEntity", "SocialNavigationHint",
        ):
            setattr(bm_msg, name, _msg_class(name))
        bm.msg = bm_msg
        sys.modules["bonbon_msgs"] = bm
        sys.modules["bonbon_msgs.msg"] = bm_msg

    # ── bonbon_srvs ───────────────────────────────────────────────────────────
    if "bonbon_srvs" not in sys.modules:
        bs = types.ModuleType("bonbon_srvs")
        bs_srv = types.ModuleType("bonbon_srvs.srv")
        for name in ("AnalyzeText", "HealthCheck", "SetPrivacyMode", "SetMode"):
            srv_cls = _msg_class(name)
            srv_cls.Request = _msg_class(f"{name}_Request")
            srv_cls.Response = _msg_class(f"{name}_Response")
            setattr(bs_srv, name, srv_cls)
        bs.srv = bs_srv
        sys.modules["bonbon_srvs"] = bs
        sys.modules["bonbon_srvs.srv"] = bs_srv


# Install at import time — runs before any test module is collected.
_install_stubs()
