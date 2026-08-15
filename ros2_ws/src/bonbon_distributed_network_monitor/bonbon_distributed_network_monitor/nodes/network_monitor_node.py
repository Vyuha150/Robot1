"""bonbon_distributed_network_monitor.nodes.network_monitor_node -- the
one ROS2 node this package needs. Runs `chronyc tracking` locally on
whichever Pi it's launched on (every Pi runs its own copy -- clock
offset is a per-machine reading, not something one Pi can observe for
another), parses it via core/chrony_offset.py, evaluates it against
config/distributed/robot_network.yaml's time_sync thresholds via
core/offset_evaluator.py, and:

  1. publishes a JSON status snapshot on
     /bonbon/network_monitor/status for the dashboard, on a timer (same
     lazy-rclpy-import, timer-tick, std_msgs/String-JSON pattern already
     established by bonbon_hardware_telemetry.nodes.hardware_telemetry_node
     and bonbon_edge_ai_runtime.nodes.edge_ai_runtime_node -- see either
     file's own docstring for why: this dev sandbox has no rclpy, so
     every node in this repo defers the import into main());
  2. publishes any triggered core/trigger.py TelemetryTrigger as a real
     bonbon_msgs/HalFault on /bonbon/hal/fault -- the ALREADY-EXISTING
     ingestion topic bonbon_fault_manager.nodes.fault_manager_node
     subscribes to, so this node does not build a second, competing
     alerting mechanism;
  3. (3-Pi Phase 7 remainder) on the same tick, TCP-connect-probes every
     OTHER Pi listed in robot_network.yaml's `pis` section (via
     core/rtt_probe.py) and evaluates RTT/packet-loss against
     network_quality thresholds (core/quality_evaluator.py) -- the
     genuine gap confirmed against this repo: heartbeat/chrony answer "is
     the peer alive" and "is my clock right," neither measures link
     quality, so a degraded-but-not-dead link (rising latency,
     intermittent loss) could look fully healthy on both.

Deliberately does NOT touch peer-Pi liveness/heartbeat state machine --
that is bonbon_distributed_safety.nodes.distributed_safety_node's job
already (real, tested, deployed); this node's RTT probe is a
complementary, independent signal, not a replacement for heartbeat.
"""

from __future__ import annotations

import subprocess


def _run_chronyc_tracking(timeout_sec: float = 5.0) -> str | None:
    """Returns raw `chronyc tracking` stdout, or None if it couldn't be
    run at all (not installed, timed out, non-zero exit) -- the caller
    turns None into core.chrony_offset.unavailable_result(), never a
    fabricated reading."""
    try:
        result = subprocess.run(
            ["chronyc", "tracking"],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def main(
    args: list[str] | None = None,
) -> None:  # pragma: no cover -- exercised only with rclpy present
    try:
        import json

        import rclpy
        from bonbon_msgs.msg import HalFault
        from rclpy.node import Node
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
        from std_msgs.msg import String
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "network_monitor_node requires rclpy + std_msgs + bonbon_msgs -- run inside a ROS2 "
            "environment, not this dev sandbox"
        ) from exc

    from bonbon_distributed_network_monitor.core.chrony_offset import (
        parse_chronyc_tracking,
        unavailable_result,
    )
    from bonbon_distributed_network_monitor.core.network_thresholds import (
        NetworkQualityThresholds,
        TimeSyncThresholds,
        load_peer_targets,
    )
    from bonbon_distributed_network_monitor.core.offset_evaluator import (
        compute_offset_metrics,
        offset_triggers,
    )
    from bonbon_distributed_network_monitor.core.quality_evaluator import (
        compute_quality_metrics,
        quality_triggers,
    )
    from bonbon_distributed_network_monitor.core.rtt_probe import probe_host
    from bonbon_distributed_network_monitor.core.trigger import TelemetryTrigger

    _QOS_RELIABLE_D10 = QoSProfile(
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.VOLATILE,
        history=HistoryPolicy.KEEP_LAST,
        depth=10,
    )

    class NetworkMonitorNode(Node):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__("network_monitor_node")
            self.declare_parameter("pi_role", "unknown_pi")
            self.declare_parameter("robot_network_config_path", "")
            self.declare_parameter("poll_interval_sec", 0.0)  # 0 = use config file's value

            self._pi_role = str(self.get_parameter("pi_role").value)
            config_path = str(self.get_parameter("robot_network_config_path").value) or None
            self._thresholds = TimeSyncThresholds.load(config_path)
            self._quality_thresholds = NetworkQualityThresholds.load(config_path)
            self._peers = load_peer_targets(self._pi_role, config_path)

            self._pub_fault = self.create_publisher(
                HalFault, "/bonbon/hal/fault", _QOS_RELIABLE_D10
            )
            self._pub_status = self.create_publisher(
                String, "/bonbon/network_monitor/status", _QOS_RELIABLE_D10
            )

            interval_param = float(self.get_parameter("poll_interval_sec").value)
            interval = interval_param if interval_param > 0 else self._thresholds.poll_interval_sec
            self._timer = self.create_timer(interval, self._on_tick)

        def _publish_trigger(self, trigger: TelemetryTrigger) -> None:
            msg = HalFault()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.device = trigger.device
            msg.driver_mode = "real"
            msg.severity = int(trigger.severity)
            msg.error_code = trigger.code
            msg.message = trigger.message
            msg.is_recovered = trigger.is_recovered
            msg.reconnect_attempt = 0
            self._pub_fault.publish(msg)

        def _on_tick(self) -> None:
            raw = _run_chronyc_tracking()
            result = (
                unavailable_result("chronyc unavailable, timed out, or exited non-zero")
                if raw is None
                else parse_chronyc_tracking(raw)
            )

            metrics = compute_offset_metrics(self._pi_role, result, self._thresholds)
            for trigger in offset_triggers(metrics):
                self._publish_trigger(trigger)

            quality_status = []
            for peer in self._peers:
                probe_result = probe_host(
                    peer.hostname,
                    self._quality_thresholds.probe_port,
                    self._quality_thresholds.probes_per_check,
                )
                q_metrics = compute_quality_metrics(
                    self._pi_role, peer.role, probe_result, self._quality_thresholds
                )
                for trigger in quality_triggers(q_metrics):
                    self._publish_trigger(trigger)
                quality_status.append(
                    {
                        "peer_role": q_metrics.peer_role,
                        "peer_host": q_metrics.peer_host,
                        "reachable": q_metrics.reachable,
                        "avg_rtt_ms": q_metrics.avg_rtt_ms,
                        "max_rtt_ms": q_metrics.max_rtt_ms,
                        "packet_loss_pct": q_metrics.packet_loss_pct,
                    }
                )

            status = String()
            status.data = json.dumps(
                {
                    "pi_role": metrics.pi_role,
                    "raw_available": metrics.raw_available,
                    "synchronised": metrics.synchronised,
                    "offset_ms": metrics.offset_ms,
                    "leap_status": metrics.leap_status,
                    "max_offset_ms": self._thresholds.max_offset_ms,
                    "alert_offset_ms": self._thresholds.alert_offset_ms,
                    "max_offset_exceeded": metrics.max_offset_exceeded,
                    "alert_offset_exceeded": metrics.alert_offset_exceeded,
                    "peer_link_quality": quality_status,
                }
            )
            self._pub_status.publish(status)

    rclpy.init(args=args)
    node = NetworkMonitorNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":  # pragma: no cover
    main()
