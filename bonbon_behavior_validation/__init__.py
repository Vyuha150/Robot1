"""Judges whether BonBon's observed behavior for a scenario was correct.

Pure Python, no rclpy/ROS2 import -- importable from CI, from
tests/production/test_*_scenarios.py, and from the dashboard backend
(bonbon_operator_api) without a sourced workspace.
"""

from bonbon_behavior_validation.behavior_oracle import (
    BehaviorOracle,
    ObservedOutcome,
    OracleVerdict,
)
from bonbon_behavior_validation.expected_outcomes import (
    CheckResult,
    CheckStatus,
    derive_expected_outcome,
)

__all__ = [
    "BehaviorOracle",
    "ObservedOutcome",
    "OracleVerdict",
    "CheckResult",
    "CheckStatus",
    "derive_expected_outcome",
]
