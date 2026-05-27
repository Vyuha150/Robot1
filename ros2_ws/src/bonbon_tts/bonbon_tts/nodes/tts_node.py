"""
bonbon_tts.nodes.tts_node
===========================
ROS2 LifecycleNode wrapping the SpeechSynthesizer.

Topics subscribed
-----------------
``/bonbon/tts/say``  (std_msgs/String)
    Plain-text utterances at NORMAL priority.

``/bonbon/tts/say_priority``  (std_msgs/String)
    JSON-encoded utterance bag::

        {
          "text":       "Hello",
          "priority":   "HIGH",   // EMERGENCY | HIGH | NORMAL | LOW
          "source":     "llm",
          "dedup_key":  "",
          "max_age_sec": 30.0,
          "interrupt":  false
        }

``/bonbon/tts/emergency``  (std_msgs/String)
    Emergency text — EMERGENCY priority, interrupt=True.

Topics published
----------------
``/bonbon/tts/health``  (std_msgs/String — JSON)
    Periodic health report at ``health_rate_hz``.

Services
--------
``/bonbon/tts/clear_queue``  (std_srvs/Empty)
    Drop all pending utterances.

Lifecycle states
----------------
``configure``  → reads params, creates SpeechSynthesizer, warms up backends
``activate``   → starts worker thread, enables subscriptions
``deactivate`` → pauses worker (drains queue gracefully)
``cleanup``    → full shutdown, releases hardware
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

try:
    import rclpy
    from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
    from std_msgs.msg import String
    from std_srvs.srv import Empty

    _ROS2_AVAILABLE = True
except ImportError:
    _ROS2_AVAILABLE = False
    logger.warning("rclpy not available — TTS node cannot run as ROS2 node")

from bonbon_tts.backends.piper_tts import PiperTTS
from bonbon_tts.config.tts_config import (
    FillerConfig,
    PiperConfig,
    QueueConfig,
    SpeakerConfig,
    TTSConfig,
)
from bonbon_tts.core.filler_player import FillerPlayer
from bonbon_tts.core.speech_synthesizer import SpeechSynthesizer
from bonbon_tts.core.utterance_queue import Priority, Utterance, UtteranceQueue
from bonbon_tts.speaker.speaker_bridge import MockSpeakerBridge


def main(args=None):
    """Entry point for the ``tts_node`` executable."""
    if not _ROS2_AVAILABLE:
        logger.error("Cannot start TTS node: rclpy is not installed")
        return

    rclpy.init(args=args)
    node = TTSNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if not _ROS2_AVAILABLE:
    # Provide a stub class so imports don't fail in test environments
    class TTSNode:  # type: ignore[no-redef]
        """Stub when ROS2 is not available."""

        pass

else:

    class TTSNode(LifecycleNode):  # type: ignore[no-redef]
        """
        Lifecycle TTS node.

        All ROS2 parameters are declared in ``on_configure`` and read
        from ``config/tts_params.yaml``.
        """

        def __init__(self) -> None:
            super().__init__("tts_node")
            self._synth: SpeechSynthesizer | None = None
            self._health_timer = None
            self._subs = []
            self._clear_srv = None

        # ── Lifecycle callbacks ────────────────────────────────────────────────

        def on_configure(self, state: State) -> TransitionCallbackReturn:
            self.get_logger().info("TTSNode: configuring")

            # Declare and read parameters
            self.declare_parameter("piper.model_path", "")
            self.declare_parameter("piper.use_subprocess", True)
            self.declare_parameter("piper.voice", "en_US-lessac-medium")
            self.declare_parameter("piper.synthesis_timeout_sec", 10.0)
            self.declare_parameter("piper.cuda", False)
            self.declare_parameter("piper.length_scale", 1.0)
            self.declare_parameter("filler.enabled", True)
            self.declare_parameter("filler.filler_dir", "")
            self.declare_parameter("filler.cooldown_sec", 3.0)
            self.declare_parameter("filler.trigger_queue_depth", 2)
            self.declare_parameter("filler.trigger_latency_ms", 400.0)
            self.declare_parameter("queue.max_depth", 32)
            self.declare_parameter("queue.dedup_enabled", True)
            self.declare_parameter("speaker.driver", "mock")
            self.declare_parameter("speaker.device", "default")
            self.declare_parameter("speaker.volume_pct", 80.0)
            self.declare_parameter("health_rate_hz", 1.0)
            self.declare_parameter("allow_degraded_startup", True)

            cfg = self._build_config()

            # Build backends
            piper = PiperTTS(cfg.piper)

            # Build speaker bridge
            speaker = self._build_speaker(cfg)

            # Build filler player
            filler = FillerPlayer(
                filler_dir=cfg.filler.filler_dir,
                cooldown_sec=cfg.filler.cooldown_sec,
                trigger_queue_depth=cfg.filler.trigger_queue_depth,
                trigger_latency_ms=cfg.filler.trigger_latency_ms,
                enabled=cfg.filler.enabled,
            )
            filler.load()

            queue = UtteranceQueue(
                max_depth=cfg.queue.max_depth,
                dedup_enabled=cfg.queue.dedup_enabled,
            )

            self._synth = SpeechSynthesizer(
                primary_tts=piper,
                speaker=speaker,
                queue=queue,
                filler=filler,
            )
            self._cfg = cfg
            self.get_logger().info("TTSNode: configured")
            return TransitionCallbackReturn.SUCCESS

        def on_activate(self, state: State) -> TransitionCallbackReturn:
            self.get_logger().info("TTSNode: activating")
            self._synth.start()

            # Subscriptions
            self._subs.append(
                self.create_subscription(
                    String,
                    "/bonbon/tts/say",
                    self._cb_say,
                    10,
                )
            )
            self._subs.append(
                self.create_subscription(
                    String,
                    "/bonbon/tts/say_priority",
                    self._cb_say_priority,
                    10,
                )
            )
            self._subs.append(
                self.create_subscription(
                    String,
                    "/bonbon/tts/emergency",
                    self._cb_emergency,
                    10,
                )
            )

            # Health publisher + timer
            self._health_pub = self.create_publisher(
                String,
                "/bonbon/tts/health",
                10,
            )
            period = 1.0 / max(0.1, self._cfg.health_rate_hz)
            self._health_timer = self.create_timer(period, self._publish_health)

            # Clear-queue service
            self._clear_srv = self.create_service(
                Empty,
                "/bonbon/tts/clear_queue",
                self._cb_clear_queue,
            )

            self.get_logger().info("TTSNode: active")
            return TransitionCallbackReturn.SUCCESS

        def on_deactivate(self, state: State) -> TransitionCallbackReturn:
            self.get_logger().info("TTSNode: deactivating")
            if self._health_timer:
                self._health_timer.cancel()
                self._health_timer = None
            for sub in self._subs:
                self.destroy_subscription(sub)
            self._subs.clear()
            if self._synth:
                self._synth.stop()
            return TransitionCallbackReturn.SUCCESS

        def on_cleanup(self, state: State) -> TransitionCallbackReturn:
            self.get_logger().info("TTSNode: cleaning up")
            self._synth = None
            return TransitionCallbackReturn.SUCCESS

        def on_shutdown(self, state: State) -> TransitionCallbackReturn:
            if self._synth:
                self._synth.stop()
            return TransitionCallbackReturn.SUCCESS

        # ── Subscription callbacks ─────────────────────────────────────────────

        def _cb_say(self, msg: String) -> None:  # type: ignore[name-defined]
            text = msg.data.strip()
            if not text:
                return
            utt = Utterance(text=text, priority=Priority.NORMAL, source="tts/say")
            self._synth.say(utt)

        def _cb_say_priority(self, msg: String) -> None:  # type: ignore[name-defined]
            try:
                data = json.loads(msg.data)
                text = data.get("text", "").strip()
                prio_str = data.get("priority", "NORMAL").upper()
                prio = Priority[prio_str]
                utt = Utterance(
                    text=text,
                    priority=prio,
                    source=data.get("source", "tts/say_priority"),
                    dedup_key=data.get("dedup_key", ""),
                    max_age_sec=float(data.get("max_age_sec", 30.0)),
                    interrupt=bool(data.get("interrupt", False)),
                )
                if text:
                    self._synth.say(utt)
            except Exception as exc:
                self.get_logger().warning(f"TTSNode: invalid say_priority payload: {exc}")

        def _cb_emergency(self, msg: String) -> None:  # type: ignore[name-defined]
            text = msg.data.strip()
            if not text:
                return
            utt = Utterance(
                text=text,
                priority=Priority.EMERGENCY,
                interrupt=True,
                source="tts/emergency",
                max_age_sec=120.0,
            )
            self._synth.say(utt)

        # ── Service callbacks ──────────────────────────────────────────────────

        def _cb_clear_queue(self, request, response):
            if self._synth:
                dropped = self._synth.queue.clear()
                self.get_logger().info(f"TTSNode: cleared queue ({dropped} items)")
            return response

        # ── Health publishing ──────────────────────────────────────────────────

        def _publish_health(self) -> None:
            if not self._synth:
                return
            try:
                report = self._synth.get_health_report()
                payload = {
                    "synthesizer_ok": report.synthesizer_ok,
                    "speaker_ok": report.speaker_ok,
                    "backend": report.backend,
                    "queue_depth": report.queue_depth,
                    "queue_overflows": report.queue_overflows,
                    "last_synthesis_ms": round(report.last_synthesis_ms, 1),
                    "mean_synthesis_ms": round(report.mean_synthesis_ms, 1),
                    "p95_synthesis_ms": round(report.p95_synthesis_ms, 1),
                    "synthesis_errors": report.synthesis_errors,
                    "fallback_count": report.fallback_count,
                    "utterances_played": report.utterances_played,
                    "uptime_sec": round(report.uptime_sec, 1),
                    "is_healthy": report.is_healthy,
                }
                msg = String()
                msg.data = json.dumps(payload)
                self._health_pub.publish(msg)
            except Exception as exc:
                self.get_logger().warning(f"TTSNode: health publish failed: {exc}")

        # ── Config builder ─────────────────────────────────────────────────────

        def _build_config(self) -> TTSConfig:
            def p(name):
                return self.get_parameter(name).value

            return TTSConfig(
                piper=PiperConfig(
                    model_path=p("piper.model_path"),
                    use_subprocess=p("piper.use_subprocess"),
                    voice=p("piper.voice"),
                    synthesis_timeout_sec=p("piper.synthesis_timeout_sec"),
                    cuda=p("piper.cuda"),
                    length_scale=p("piper.length_scale"),
                ),
                filler=FillerConfig(
                    enabled=p("filler.enabled"),
                    filler_dir=p("filler.filler_dir"),
                    cooldown_sec=p("filler.cooldown_sec"),
                    trigger_queue_depth=p("filler.trigger_queue_depth"),
                    trigger_latency_ms=p("filler.trigger_latency_ms"),
                ),
                queue=QueueConfig(
                    max_depth=p("queue.max_depth"),
                    dedup_enabled=p("queue.dedup_enabled"),
                ),
                speaker=SpeakerConfig(
                    driver=p("speaker.driver"),
                    device=p("speaker.device"),
                    volume_pct=p("speaker.volume_pct"),
                ),
                health_rate_hz=p("health_rate_hz"),
                allow_degraded_startup=p("allow_degraded_startup"),
            )

        def _build_speaker(self, cfg: TTSConfig) -> MockSpeakerBridge:
            """Build speaker bridge; always returns MockSpeakerBridge if HAL absent."""
            if cfg.speaker.driver == "hal":
                try:
                    from bonbon_tts.speaker.speaker_bridge import SpeakerBridge

                    return SpeakerBridge(
                        device=cfg.speaker.device,
                        volume_pct=cfg.speaker.volume_pct,
                        sample_rate=cfg.speaker.sample_rate,
                        channels=cfg.speaker.channels,
                    )
                except ImportError:
                    self.get_logger().warning("bonbon_hal not available; using MockSpeakerBridge")
            return MockSpeakerBridge()
