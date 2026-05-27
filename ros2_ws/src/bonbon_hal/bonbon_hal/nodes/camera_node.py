"""
HAL camera node — Orbbec Astra Mini RGB-D.

Publishes:
  /bonbon/vision/camera/color/image_raw    (sensor_msgs/Image)
  /bonbon/vision/camera/color/camera_info  (sensor_msgs/CameraInfo)
  /bonbon/vision/camera/depth/image_raw    (sensor_msgs/Image)
  /bonbon/vision/camera_node/health        (bonbon_msgs/ModuleHealth)
"""

from __future__ import annotations

import rclpy
from sensor_msgs.msg import CameraInfo, Image

from bonbon_hal.base.driver_base import DriverBase
from bonbon_hal.drivers.camera import MockCameraDriver, OrbbecDriver

from .hal_node_base import BEST_EFFORT_D5, HalNodeBase


class CameraNode(HalNodeBase):
    NODE_NAME = "camera_node"
    DEVICE_NAME = "camera"
    HEALTH_TOPIC = "/bonbon/vision/camera_node/health"
    DEFAULT_RATE_HZ = 30.0

    def __init__(self) -> None:
        super().__init__()
        self.declare_parameter("width", 640)
        self.declare_parameter("height", 480)
        self.declare_parameter("fps", 30)
        self.declare_parameter("frame_id_color", "camera_color_optical_frame")
        self.declare_parameter("frame_id_depth", "camera_depth_optical_frame")
        self._pub_color = None
        self._pub_depth = None
        self._pub_color_info = None

    def _create_driver(self) -> DriverBase:
        w = self.get_parameter("width").value
        h = self.get_parameter("height").value
        f = self.get_parameter("fps").value
        if self.get_parameter("driver_mode").value == "real":
            return OrbbecDriver(width=w, height=h, fps=f)
        return MockCameraDriver(width=w, height=h, fps=f)

    def _create_publishers(self) -> None:
        self._pub_color = self.create_lifecycle_publisher(
            Image, "/bonbon/vision/camera/color/image_raw", BEST_EFFORT_D5
        )
        self._pub_depth = self.create_lifecycle_publisher(
            Image, "/bonbon/vision/camera/depth/image_raw", BEST_EFFORT_D5
        )
        self._pub_color_info = self.create_lifecycle_publisher(
            CameraInfo, "/bonbon/vision/camera/color/camera_info", BEST_EFFORT_D5
        )

    def _publish_data(self) -> None:
        color, depth = self._driver.read_frames()
        now = self.get_clock().now().to_msg()

        if color is not None:
            msg = Image()
            msg.header.stamp = now
            msg.header.frame_id = self.get_parameter("frame_id_color").value
            msg.width = color.width
            msg.height = color.height
            msg.encoding = color.encoding
            msg.step = color.width * 3
            msg.data = list(color.data)
            self._pub_color.publish(msg)

            # Camera info
            ci = CameraInfo()
            ci.header = msg.header
            ci.width = color.width
            ci.height = color.height
            intr = self._driver.get_intrinsics()
            ci.k = [intr["fx"], 0, intr["cx"], 0, intr["fy"], intr["cy"], 0, 0, 1.0]
            ci.distortion_model = "plumb_bob"
            self._pub_color_info.publish(ci)

        if depth is not None:
            msg = Image()
            msg.header.stamp = now
            msg.header.frame_id = self.get_parameter("frame_id_depth").value
            msg.width = depth.width
            msg.height = depth.height
            msg.encoding = "32FC1"
            msg.step = depth.width * 4
            msg.data = list(depth.data.astype("float32").tobytes())
            self._pub_depth.publish(msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = CameraNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
