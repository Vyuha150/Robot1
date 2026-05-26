"""
bonbon_navigation.nodes — ROS2 node entry points.

Import is lazy to avoid rclpy import at package load time
(allows unit tests to run without a live ROS2 environment).
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bonbon_navigation.nodes.navigation_node import NavigationNode


def __getattr__(name: str):
    if name == "NavigationNode":
        from bonbon_navigation.nodes.navigation_node import NavigationNode
        return NavigationNode
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["NavigationNode"]
