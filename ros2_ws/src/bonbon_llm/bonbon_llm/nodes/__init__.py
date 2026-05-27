"""
bonbon_llm.nodes
================
ROS2 LifecycleNode(s) for the LLM + Response Generation Module.
"""

# Note: importing LLMOrchestratorNode here would trigger rclpy import,
# which may fail outside a ROS2 environment.  Import it explicitly when needed.

__all__ = ["LLMOrchestratorNode"]


def __getattr__(name: str):
    if name == "LLMOrchestratorNode":
        from bonbon_llm.nodes.llm_orchestrator_node import LLMOrchestratorNode

        return LLMOrchestratorNode
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
