"""
HAL LIDAR node — RPLIDAR S2.

Publishes:
  /bonbon/lidar/scan                 (sensor_msgs/LaserScan)  RELIABLE
  /bonbon/spatial/lidar_node/health  (bonbon_msgs/ModuleHealth)

The topic /bonbon/lidar/scan matches the safety supervisor subscription.
"""

from __future__ import annotations

import rclpy
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import LaserScan

from bonbon_hal.base.driver_base import DriverBase
from bonbon_hal.drivers.lidar import MockLidarDriver, RplidarDriver

from .hal_node_base import HalNodeBase

SENSOR_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    history=HistoryPolicy.KEEP_LAST,
    depth=5,
)


class LidarNode(HalNodeBase):
    NODE_NAME = "lidar_node"
    DEVICE_NAME = "lidar"
    HEALTH_TOPIC = "/bonbon/spatial/lidar_node/health"
    DEFAULT_RATE_HZ = 10.0

    def __init__(self) -> None:
        super().__init__()
        self.declare_parameter("port", "/dev/ttyUSB0")
        self.declare_parameter("baudrate", 115200)
        self._pub_scan = None

    def _create_driver(self) -> DriverBase:
        mode = self.get_parameter("driver_mode").value
        if mode == "real":
            return RplidarDriver(
                port=self.get_parameter("port").value,
                baudrate=self.get_parameter("baudrate").value,
            )
        return MockLidarDriver()

    def _create_publishers(self) -> None:
        self._pub_scan = self.create_lifecycle_publisher(
            LaserScan, "/bonbon/lidar/scan", SENSOR_QOS
        )

    def _publish_data(self) -> None:
        from bonbon_hal.drivers.lidar.lidar_driver import LidarScan

        scan: LidarScan = self._driver.read_scan()

        msg = LaserScan()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "lidar_link"
        msg.angle_min = scan.angle_min_rad
        msg.angle_max = scan.angle_max_rad
        msg.angle_increment = scan.angle_increment_rad
        msg.time_increment = scan.time_increment_sec
        msg.scan_time = scan.scan_time_sec
        msg.range_min = scan.range_min_m
        msg.range_max = scan.range_max_m
        msg.ranges = [float(r) for r in scan.ranges]
        msg.intensities = [float(i) for i in scan.intensities]
        self._pub_scan.publish(msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = LidarNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
