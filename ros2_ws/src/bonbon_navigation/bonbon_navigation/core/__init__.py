"""bonbon_navigation.core — Core navigation subsystems."""

from bonbon_navigation.core.battery_router import (
    BatteryLevel,
    BatteryRouter,
    BatteryState,
    RoutingDecision,
)
from bonbon_navigation.core.goal_manager import (
    RESULT_CANCELLED,
    RESULT_NONE,
    RESULT_PLAN_FAILED,
    RESULT_SAFETY_STOP,
    RESULT_STUCK,
    RESULT_SUCCESS,
    RESULT_TIMEOUT,
    RESULT_UNREACHABLE,
    GoalManager,
    GoalState,
    NavigationGoalEntry,
)
from bonbon_navigation.core.localization_monitor import (
    LocalizationMonitor,
    LocalizationQuality,
    LocalizationReport,
    PoseEstimate,
)
from bonbon_navigation.core.map_manager import (
    MapInfo,
    MapManager,
    NamedPose,
)
from bonbon_navigation.core.recovery_executor import (
    RecoveryExecutor,
    RecoveryOutcome,
    RecoveryState,
)
from bonbon_navigation.core.stuck_detector import (
    PositionSample,
    StuckDetector,
    StuckResult,
)

__all__ = [
    # map_manager
    "MapInfo",
    "NamedPose",
    "MapManager",
    # localization_monitor
    "LocalizationQuality",
    "PoseEstimate",
    "LocalizationReport",
    "LocalizationMonitor",
    # stuck_detector
    "PositionSample",
    "StuckResult",
    "StuckDetector",
    # goal_manager
    "GoalState",
    "NavigationGoalEntry",
    "GoalManager",
    "RESULT_NONE",
    "RESULT_SUCCESS",
    "RESULT_CANCELLED",
    "RESULT_TIMEOUT",
    "RESULT_STUCK",
    "RESULT_SAFETY_STOP",
    "RESULT_UNREACHABLE",
    "RESULT_PLAN_FAILED",
    # battery_router
    "BatteryLevel",
    "BatteryState",
    "RoutingDecision",
    "BatteryRouter",
    # recovery_executor
    "RecoveryOutcome",
    "RecoveryState",
    "RecoveryExecutor",
]
