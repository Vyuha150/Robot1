"""
HAL speaker node — ALSA.

Subscribes:
  /bonbon/speech/audio_output        (bonbon_msgs/AudioChunk) — play audio
  /bonbon/tts/audio_file             (std_msgs/String) — play WAV file path

Publishes:
  /bonbon/speech/speaker_node/health (bonbon_msgs/ModuleHealth)
"""

from __future__ import annotations

import rclpy
from bonbon_msgs.msg import AudioChunk
from std_msgs.msg import String

from bonbon_hal.base.driver_base import DriverBase
from bonbon_hal.drivers.microphone.mic_driver import AudioChunk as AC
from bonbon_hal.drivers.speaker import AlsaSpeakerDriver, MockSpeakerDriver

from .hal_node_base import RELIABLE_D10, HalNodeBase


class SpeakerNode(HalNodeBase):
    NODE_NAME = "speaker_node"
    DEVICE_NAME = "speaker"
    HEALTH_TOPIC = "/bonbon/speech/speaker_node/health"
    DEFAULT_RATE_HZ = 1.0  # health only; audio is event-driven

    def __init__(self) -> None:
        super().__init__()
        self.declare_parameter("volume_pct", 80.0)
        self.declare_parameter("alsa_device", "default")
        self.declare_parameter("amixer_control", "Master")

    def _create_driver(self) -> DriverBase:
        vol = self.get_parameter("volume_pct").value
        if self.get_parameter("driver_mode").value == "real":
            return AlsaSpeakerDriver(
                device_name=self.get_parameter("alsa_device").value,
                volume_pct=vol,
                amixer_control=self.get_parameter("amixer_control").value,
            )
        return MockSpeakerDriver()

    def _create_publishers(self) -> None:
        pass  # Speaker node only publishes health (via base class)

    def _create_subscribers(self) -> None:
        self.create_subscription(
            AudioChunk, "/bonbon/speech/audio_output", self._cb_audio, RELIABLE_D10
        )
        self.create_subscription(
            String, "/bonbon/tts/audio_file", self._cb_audio_file, RELIABLE_D10
        )

    def _cb_audio(self, msg: AudioChunk) -> None:
        if not self._driver or not self._driver.is_connected:
            return
        try:
            import struct

            raw = struct.pack(f"<{len(msg.data)}h", *[int(s * 32767) for s in msg.data])
            chunk = AC(
                data=raw,
                sample_rate=msg.sample_rate,
                channels=msg.channels,
                bit_depth=msg.bit_depth,
            )
            self._driver.play(chunk)
        except Exception as exc:
            self.get_logger().warning(f"Speaker play failed: {exc}")

    def _cb_audio_file(self, msg: String) -> None:
        if not self._driver or not self._driver.is_connected:
            return
        try:
            self._driver.play_file(msg.data)
        except Exception as exc:
            self.get_logger().warning(f"Speaker play_file failed: {exc}")

    def _publish_data(self) -> None:
        pass  # No periodic data; health is published by base class


def main(args=None) -> None:
    rclpy.init(args=args)
    node = SpeakerNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
