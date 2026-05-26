"""
bonbon_navigation
=================
Autonomous navigation module for the BonBon service robot.

Provides:
  - Nav2 integration with RTAB-Map SLAM / localization
  - Priority goal queue with preemption
  - Human-aware local costmap inflation
  - Stuck detection and recovery cascade
  - Precision docking with ArUco + IR beacon fusion
  - Battery-aware routing
  - Safety stop bridge (all velocity gated through SafetyStopBridge)

Architecture
------------
NavigationNode (LifecycleNode)
  ├─ GoalManager          — priority queue, timeout tracking
  ├─ StuckDetector        — rolling window progress / zero-velocity
  ├─ RecoveryExecutor     — wait / clear_costmap / backup / spin / replan / announce / escalate
  ├─ DockingController    — APPROACHING → ALIGNING → FINAL_APPROACH → CONTACT
  ├─ BatteryRouter        — LOW/CRITICAL routing decisions
  ├─ HumanAwareCostmapLayer — inflated cost grid around tracked persons
  ├─ LocalizationMonitor  — RTAB-Map + AMCL quality tracking
  ├─ MapManager           — PGM/YAML loader, named-location registry
  └─ SafetyStopBridge     — ALL cmd_vel gated here (never direct to /cmd_vel)

Security
--------
  * Navigation node NEVER publishes directly to /cmd_vel.
  * All velocity commands:
      NavigationNode → SafetyStopBridge → /bonbon/safety_gate/cmd_vel
      → SafetyGateNode → /cmd_vel
"""

__version__ = "1.0.0"
__all__ = ["__version__"]
