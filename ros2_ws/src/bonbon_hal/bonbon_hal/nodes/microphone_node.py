"""
HAL microphone node — ReSpeaker v2.0.

Publishes:
  /bonbon/speech/audio               (bonbon_msgs/AudioChunk)
  /bonbon/speech/mic_node/health     (bonbon_msgs/ModuleHealth)
"""

from __future__ import annotations

import rclpy
from bonbon_msgs.msg import AudioChunk

from bonbon_hal.base.driver_base import DriverBase
from bonbon_hal.drivers.microphone import MockMicDriver, RespeakerDriver

from .hal_node_base import BEST_EFFORT_D5, HalNodeBase


class MicrophoneNode(HalNodeBase):
    NODE_NAME = "mic_node"
    DEVICE_NAME = "microphone"
    HEALTH_TOPIC = "/bonbon/speech/mic_node/health"
    DEFAULT_RATE_HZ = 16.0  # 16 chunks/s × 1024 frames = 16kHz

    def __init__(self) -> None:
        super().__init__()
        self.declare_parameter("sample_rate", 16000)
        self.declare_parameter("channels", 1)
        self.declare_parameter("chunk_frames", 1024)
        self._pub_audio = None

    def _create_driver(self) -> DriverBase:
        sr = self.get_parameter("sample_rate").value
        ch = self.get_parameter("channels").value
        if self.get_parameter("driver_mode").value == "real":
            return RespeakerDriver(sample_rate=sr)
        return MockMicDriver(sample_rate=sr, channels=ch)

    def _create_publishers(self) -> None:
        self._pub_audio = self.create_lifecycle_publisher(
            AudioChunk, "/bonbon/speech/audio", BEST_EFFORT_D5
        )

    def _publish_data(self) -> None:
        from bonbon_hal.drivers.microphone.mic_driver import AudioChunk as AC

        frames = self.get_parameter("chunk_frames").value
        chunk: AC = self._driver.read_chunk(frames)

        msg = AudioChunk()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.sample_rate = chunk.sample_rate
        msg.channels = chunk.channels
        msg.bit_depth = chunk.bit_depth
        msg.doa_angle_deg = chunk.doa_angle_deg
        msg.device_id = chunk.device_id
        # Convert int16 bytes → float32 samples
        import array as _array

        samples = _array.array("h", chunk.data)
        msg.data = [s / 32768.0 for s in samples]
        self._pub_audio.publish(msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MicrophoneNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
