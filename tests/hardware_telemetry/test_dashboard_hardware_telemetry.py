"""bonbon_operator_api.websocket.hardware_telemetry_snapshots -- confirms
the relay function honestly reports unavailable when no bridge/message
exists yet (rule 11: dashboard must show real status, not a fake green
default), and correctly relays real bridge state when present. Doesn't
need rclpy -- hardware_telemetry_snapshot() only touches the fake
`app.state.ros2_bridge` object, mirroring tests/edge_ai
/test_dashboard_edge_ai.py's own no-rclpy-needed style."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

_OPERATOR_API_SRC = Path(__file__).resolve().parents[2] / "ros2_ws" / "src" / "bonbon_operator_api"
if str(_OPERATOR_API_SRC) not in sys.path:
    sys.path.insert(0, str(_OPERATOR_API_SRC))


def _fake_app(bridge=None):
    return SimpleNamespace(state=SimpleNamespace(ros2_bridge=bridge))


class TestHardwareTelemetrySnapshot(unittest.TestCase):
    def test_no_bridge_is_honestly_unavailable(self):
        from bonbon_operator_api.websocket.hardware_telemetry_snapshots import (
            hardware_telemetry_snapshot,
        )

        result = hardware_telemetry_snapshot(_fake_app(bridge=None))
        self.assertFalse(result["available"])
        self.assertIn("message", result)

    def test_bridge_with_no_message_yet_is_honestly_unavailable(self):
        from bonbon_operator_api.websocket.hardware_telemetry_snapshots import (
            hardware_telemetry_snapshot,
        )

        bridge = SimpleNamespace(get_hardware_telemetry_snapshot=lambda: None)
        result = hardware_telemetry_snapshot(_fake_app(bridge=bridge))
        self.assertFalse(result["available"])
        self.assertIn("hardware_telemetry_node", result["message"])

    def test_bridge_with_real_snapshot_relays_it_verbatim(self):
        from bonbon_operator_api.websocket.hardware_telemetry_snapshots import (
            hardware_telemetry_snapshot,
        )

        real_snapshot = {"pi_role": "navigation_safety_pi", "battery": {"percent": 80.0}}
        bridge = SimpleNamespace(get_hardware_telemetry_snapshot=lambda: real_snapshot)
        result = hardware_telemetry_snapshot(_fake_app(bridge=bridge))
        self.assertTrue(result["available"])
        self.assertEqual(result["pi_role"], "navigation_safety_pi")
        self.assertEqual(result["battery"]["percent"], 80.0)

    def test_channel_registered_under_hardware_telemetry_name(self):
        from bonbon_operator_api.websocket.hardware_telemetry_snapshots import (
            HARDWARE_TELEMETRY_CHANNEL_SNAPSHOTS,
        )

        self.assertIn("hardware-telemetry", HARDWARE_TELEMETRY_CHANNEL_SNAPSHOTS)


if __name__ == "__main__":
    unittest.main()
