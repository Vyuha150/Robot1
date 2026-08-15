"""ROS2 topic pub->sub latency probe.

Publishes a timestamped message on a topic and measures the delay until a
subscriber callback observes it, on the SAME process (no network hop --
this measures ROS2/DDS + Python callback overhead, not inter-Pi network
latency; see three_pi_network_benchmark.py for that). rclpy is imported
lazily inside `run()`, never at module scope, matching every ROS2 node in
this repo's "importable without ROS2 installed" convention -- this dev
environment has no rclpy (confirmed), so `run()` here honestly returns a
BLOCKED metric rather than raising an ImportError the caller has to catch.
"""

from __future__ import annotations

import time

import bonbon_benchmarks  # noqa: F401
from bonbon_benchmarks.metrics_collector import BenchmarkMetric, MetricSampler


def rclpy_available() -> bool:
    try:
        import rclpy  # noqa: F401
    except ImportError:
        return False
    return True


def run(
    topic: str = "/bonbon/benchmark/latency_probe",
    iterations: int = 100,
    board: str = "dev_sandbox",
) -> BenchmarkMetric:
    if not rclpy_available():
        return BenchmarkMetric.blocked(
            metric_name="ros2_topic_latency",
            board=board,
            module="ros2",
            scenario=f"pub->sub round trip on {topic}",
            reason="rclpy not importable in this environment -- no ROS2 installation",
            recommendation="Run on a Pi with the ROS2 workspace sourced (source install/setup.bash).",
        )

    import rclpy  # noqa: PLC0415
    from std_msgs.msg import String  # noqa: PLC0415

    rclpy.init(args=None)
    node = rclpy.create_node("bonbon_benchmark_latency_probe")
    sampler = MetricSampler()
    received: list[float] = []

    def _on_message(msg: String) -> None:
        sent_ns = int(msg.data)
        received.append((time.perf_counter_ns() - sent_ns) / 1_000_000.0)

    sub = node.create_subscription(String, topic, _on_message, 10)
    pub = node.create_publisher(String, topic, 10)

    try:
        for _ in range(iterations):
            msg = String()
            msg.data = str(time.perf_counter_ns())
            pub.publish(msg)
            deadline = time.time() + 1.0
            start_count = len(received)
            while len(received) == start_count and time.time() < deadline:
                rclpy.spin_once(node, timeout_sec=0.05)
        sampler.extend(received)
    finally:
        node.destroy_subscription(sub)
        node.destroy_publisher(pub)
        node.destroy_node()
        rclpy.shutdown()

    return BenchmarkMetric.from_sampler(
        sampler, metric_name="ros2_topic_latency", board=board, module="ros2",
        scenario=f"pub->sub round trip on {topic} ({iterations} messages, same-process)",
        unit="ms",
    )
