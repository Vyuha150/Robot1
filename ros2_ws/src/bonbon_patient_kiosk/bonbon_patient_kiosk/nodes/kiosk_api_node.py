"""KioskAPINode — ROS2 LifecycleNode that hosts the patient kiosk FastAPI server.

Lifecycle mirrors bonbon_operator_api's OperatorAPINode:
  configure  -> load config, create KioskAPIServer
  activate   -> start uvicorn (+ its own ROS2 bridge)
  deactivate -> stop uvicorn
  cleanup    -> release resources
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from rcl_interfaces.msg import ParameterDescriptor
    from rclpy.lifecycle import LifecycleNode, TransitionCallbackReturn

    _ROS2_AVAILABLE = True
except ImportError:
    _ROS2_AVAILABLE = False
    logger.warning("rclpy not available — KioskAPINode not functional")

from bonbon_patient_kiosk.config.kiosk_api_config import KioskAPIConfig
from bonbon_patient_kiosk.main import KioskAPIServer

if _ROS2_AVAILABLE:

    class KioskAPINode(LifecycleNode):
        def __init__(self) -> None:
            super().__init__("bonbon_patient_kiosk")
            self._server: KioskAPIServer | None = None
            self._declare_params()

        def _declare_params(self) -> None:
            self.declare_parameter(
                "host", "0.0.0.0", ParameterDescriptor(description="API server bind host")
            )
            self.declare_parameter("port", 8090, ParameterDescriptor(description="API server port"))
            self.declare_parameter("log_level", "INFO", ParameterDescriptor(description="Log level"))
            self.declare_parameter(
                "ros2_enabled", True, ParameterDescriptor(description="Enable ROS2 bridge")
            )

        def on_configure(self, state) -> TransitionCallbackReturn:
            try:
                cfg = KioskAPIConfig()
                cfg.server.host = self.get_parameter("host").value
                cfg.server.port = self.get_parameter("port").value
                cfg.server.log_level = self.get_parameter("log_level").value
                cfg.ros2.enabled = self.get_parameter("ros2_enabled").value
                self._server = KioskAPIServer(cfg)
                self.get_logger().info("KioskAPINode configured")
                return TransitionCallbackReturn.SUCCESS
            except Exception as exc:
                self.get_logger().error(f"configure failed: {exc}")
                return TransitionCallbackReturn.FAILURE

        def on_activate(self, state) -> TransitionCallbackReturn:
            try:
                if self._server:
                    self._server.start()
                self.get_logger().info("KioskAPINode activated")
                return TransitionCallbackReturn.SUCCESS
            except Exception as exc:
                self.get_logger().error(f"activate failed: {exc}")
                return TransitionCallbackReturn.FAILURE

        def on_deactivate(self, state) -> TransitionCallbackReturn:
            try:
                if self._server:
                    self._server.stop()
                self.get_logger().info("KioskAPINode deactivated")
                return TransitionCallbackReturn.SUCCESS
            except Exception as exc:
                self.get_logger().error(f"deactivate failed: {exc}")
                return TransitionCallbackReturn.FAILURE

        def on_cleanup(self, state) -> TransitionCallbackReturn:
            self._server = None
            self.get_logger().info("KioskAPINode cleaned up")
            return TransitionCallbackReturn.SUCCESS

        def on_shutdown(self, state) -> TransitionCallbackReturn:
            if self._server:
                self._server.stop()
            return TransitionCallbackReturn.SUCCESS


def main(args=None):
    if not _ROS2_AVAILABLE:
        logger.error("Cannot start KioskAPINode: rclpy not available")
        return
    import rclpy

    rclpy.init(args=args)
    node = KioskAPINode()
    executor = rclpy.executors.SingleThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
