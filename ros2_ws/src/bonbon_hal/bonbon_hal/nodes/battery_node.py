"""
HAL battery node — INA226 power monitor.

Publishes:
  /bonbon/battery/state              (sensor_msgs/BatteryState)
  /bonbon/power/battery_node/health  (bonbon_msgs/ModuleHealth)
"""

from __future__ import annotations

import rclpy
from sensor_msgs.msg import BatteryState

from bonbon_hal.base.driver_base import DriverBase
from bonbon_hal.drivers.battery import Ina226Driver, MockBatteryDriver

from .hal_node_base import RELIABLE_D10, HalNodeBase


class BatteryNode(HalNodeBase):
    NODE_NAME = "battery_node"
    DEVICE_NAME = "battery"
    HEALTH_TOPIC = "/bonbon/power/battery_node/health"
    DEFAULT_RATE_HZ = 1.0

    def __init__(self) -> None:
        super().__init__()
        self.declare_parameter("i2c_bus", 1)
        self.declare_parameter("i2c_addr", 0x40)
        self.declare_parameter("shunt_ohm", 0.01)
        self.declare_parameter("capacity_ah", 40.0)
        self._pub_battery = None

    def _create_driver(self) -> DriverBase:
        if self.get_parameter("driver_mode").value == "real":
            return Ina226Driver(
                bus=self.get_parameter("i2c_bus").value,
                address=self.get_parameter("i2c_addr").value,
                shunt_ohm=self.get_parameter("shunt_ohm").value,
                capacity_ah=self.get_parameter("capacity_ah").value,
            )
        return MockBatteryDriver()

    def _create_publishers(self) -> None:
        self._pub_battery = self.create_lifecycle_publisher(
            BatteryState, "/bonbon/battery/state", RELIABLE_D10
        )

    def _publish_data(self) -> None:
        from bonbon_hal.drivers.battery.battery_driver import BatteryReading

        r: BatteryReading = self._driver.read()
        msg = BatteryState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.voltage = r.voltage_v
        msg.current = r.current_a
        msg.charge = r.percent / 100.0 * self.get_parameter("capacity_ah").value
        msg.capacity = self.get_parameter("capacity_ah").value
        msg.design_capacity = msg.capacity
        msg.percentage = r.percent / 100.0
        msg.power_supply_status = (
            BatteryState.POWER_SUPPLY_STATUS_CHARGING
            if r.is_charging
            else BatteryState.POWER_SUPPLY_STATUS_DISCHARGING
        )
        msg.power_supply_health = BatteryState.POWER_SUPPLY_HEALTH_GOOD
        msg.power_supply_technology = BatteryState.POWER_SUPPLY_TECHNOLOGY_LIPO
        msg.present = True
        self._pub_battery.publish(msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = BatteryNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
