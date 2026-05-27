"""
HAL IMU node — MPU-6050.

Publishes:
  /bonbon/imu/data_raw               (sensor_msgs/Imu)         RELIABLE
  /bonbon/temperature/readings       (bonbon_msgs/ThermalReadings)
  /bonbon/spatial/imu_node/health    (bonbon_msgs/ModuleHealth)
"""

from __future__ import annotations

import rclpy
from bonbon_msgs.msg import ThermalReadings
from sensor_msgs.msg import Imu

from bonbon_hal.base.driver_base import DriverBase
from bonbon_hal.drivers.imu import MockImuDriver, Mpu6050Driver

from .hal_node_base import RELIABLE_D10, HalNodeBase


class ImuNode(HalNodeBase):
    NODE_NAME = "imu_node"
    DEVICE_NAME = "imu"
    HEALTH_TOPIC = "/bonbon/spatial/imu_node/health"
    DEFAULT_RATE_HZ = 100.0

    def __init__(self) -> None:
        super().__init__()
        self.declare_parameter("i2c_bus", 1)
        self.declare_parameter("i2c_addr", 0x68)
        self.declare_parameter("frame_id", "imu_link")
        self.declare_parameter("run_calibration", False)
        self._pub_imu = None
        self._pub_temp = None

    def _create_driver(self) -> DriverBase:
        mode = self.get_parameter("driver_mode").value
        if mode == "real":
            drv = Mpu6050Driver(
                bus=self.get_parameter("i2c_bus").value,
                address=self.get_parameter("i2c_addr").value,
            )
            return drv
        return MockImuDriver()

    def _create_publishers(self) -> None:
        self._pub_imu = self.create_lifecycle_publisher(Imu, "/bonbon/imu/data_raw", RELIABLE_D10)
        self._pub_temp = self.create_lifecycle_publisher(
            ThermalReadings, "/bonbon/temperature/readings", RELIABLE_D10
        )

    def on_activate(self, state):
        ret = super().on_activate(state)
        if (
            ret.value == 0  # SUCCESS
            and self.get_parameter("run_calibration").value
            and self._driver.is_connected
        ):
            try:
                self.get_logger().info("Running IMU calibration…")
                self._driver.calibrate()
            except Exception as exc:
                self.get_logger().warning(f"IMU calibration failed: {exc}")
        return ret

    def _publish_data(self) -> None:
        from bonbon_hal.drivers.imu.imu_driver import ImuReading

        reading: ImuReading = self._driver.read()
        now = self.get_clock().now().to_msg()

        # IMU message
        imu = Imu()
        imu.header.stamp = now
        imu.header.frame_id = self.get_parameter("frame_id").value
        imu.linear_acceleration.x = reading.accel_x
        imu.linear_acceleration.y = reading.accel_y
        imu.linear_acceleration.z = reading.accel_z
        imu.angular_velocity.x = reading.gyro_x
        imu.angular_velocity.y = reading.gyro_y
        imu.angular_velocity.z = reading.gyro_z
        if reading.orientation_valid:
            imu.orientation.x = reading.orient_x
            imu.orientation.y = reading.orient_y
            imu.orientation.z = reading.orient_z
            imu.orientation.w = reading.orient_w
        else:
            imu.orientation_covariance[0] = -1.0  # signal "not available"
        cov_a = reading.accel_covariance if reading.accel_covariance >= 0 else 0.0
        cov_g = reading.gyro_covariance if reading.gyro_covariance >= 0 else 0.0
        imu.linear_acceleration_covariance[0] = cov_a
        imu.linear_acceleration_covariance[4] = cov_a
        imu.linear_acceleration_covariance[8] = cov_a
        imu.angular_velocity_covariance[0] = cov_g
        imu.angular_velocity_covariance[4] = cov_g
        imu.angular_velocity_covariance[8] = cov_g
        self._pub_imu.publish(imu)

        # Thermal readings (CPU temp not available from IMU alone; IMU board temp is published)
        temp_msg = ThermalReadings()
        temp_msg.header.stamp = now
        temp_msg.cpu_temp_c = 0.0  # set by dedicated thermal monitor
        temp_msg.motor_temp_c = 0.0
        temp_msg.battery_temp_c = 0.0
        temp_msg.board_temp_c = reading.temperature_c
        self._pub_temp.publish(temp_msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ImuNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
