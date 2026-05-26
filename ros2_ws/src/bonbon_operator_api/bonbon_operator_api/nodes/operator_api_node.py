"""OperatorAPINode — ROS2 LifecycleNode that hosts the FastAPI server.

Lifecycle
---------
  configure  → load config, create OperatorAPIServer
  activate   → start uvicorn + ROS2 bridge
  deactivate → stop uvicorn + ROS2 bridge
  cleanup    → release resources
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from rclpy.lifecycle import LifecycleNode, TransitionCallbackReturn
    from rcl_interfaces.msg import ParameterDescriptor
    _ROS2_AVAILABLE = True
except ImportError:
    _ROS2_AVAILABLE = False
    logger.warning("rclpy not available — OperatorAPINode not functional")

from bonbon_operator_api.config.api_config import OperatorAPIConfig
from bonbon_operator_api.main import OperatorAPIServer


if _ROS2_AVAILABLE:

    class OperatorAPINode(LifecycleNode):
        """ROS2 LifecycleNode for the BonBon Operator API."""

        def __init__(self) -> None:
            super().__init__("bonbon_operator_api")
            self._server: OperatorAPIServer | None = None
            self._declare_params()

        def _declare_params(self) -> None:
            self.declare_parameter(
                "host", "0.0.0.0",
                ParameterDescriptor(description="API server bind host")
            )
            self.declare_parameter(
                "port", 8080,
                ParameterDescriptor(description="API server port")
            )
            self.declare_parameter(
                "log_level", "INFO",
                ParameterDescriptor(description="Log level")
            )
            self.declare_parameter(
                "ros2_enabled", True,
                ParameterDescriptor(description="Enable ROS2 bridge")
            )
            self.declare_parameter(
                "offline_timeout_sec", 15.0,
                ParameterDescriptor(description="Seconds before robot marked offline")
            )

        # ------------------------------------------------------------------
        # Lifecycle callbacks
        # ------------------------------------------------------------------

        def on_configure(self, state) -> TransitionCallbackReturn:
            try:
                cfg = OperatorAPIConfig()
                # Override from ROS2 params
                cfg.server.host = self.get_parameter("host").value
                cfg.server.port = self.get_parameter("port").value
                cfg.server.log_level = self.get_parameter("log_level").value
                cfg.ros2.enabled = self.get_parameter("ros2_enabled").value
                cfg.ros2.offline_timeout_sec = self.get_parameter(
                    "offline_timeout_sec"
                ).value
                self._server = OperatorAPIServer(cfg)
                self.get_logger().info("OperatorAPINode configured")
                return TransitionCallbackReturn.SUCCESS
            except Exception as exc:
                self.get_logger().error(f"configure failed: {exc}")
                return TransitionCallbackReturn.FAILURE

        def on_activate(self, state) -> TransitionCallbackReturn:
            try:
                if self._server:
                    self._server.start()
                self.get_logger().info("OperatorAPINode activated")
                return TransitionCallbackReturn.SUCCESS
            except Exception as exc:
                self.get_logger().error(f"activate failed: {exc}")
                return TransitionCallbackReturn.FAILURE

        def on_deactivate(self, state) -> TransitionCallbackReturn:
            try:
                if self._server:
                    self._server.stop()
                self.get_logger().info("OperatorAPINode deactivated")
                return TransitionCallbackReturn.SUCCESS
            except Exception as exc:
                self.get_logger().error(f"deactivate failed: {exc}")
                return TransitionCallbackReturn.FAILURE

        def on_cleanup(self, state) -> TransitionCallbackReturn:
            self._server = None
            self.get_logger().info("OperatorAPINode cleaned up")
            return TransitionCallbackReturn.SUCCESS

        def on_shutdown(self, state) -> TransitionCallbackReturn:
            if self._server:
                self._server.stop()
            return TransitionCallbackReturn.SUCCESS


def main(args=None):
    if not _ROS2_AVAILABLE:
        logger.error("Cannot start OperatorAPINode: rclpy not available")
        return
    import rclpy
    rclpy.init(args=args)
    node = OperatorAPINode()
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
