"""
bonbon_navigation.config.nav_config
=====================================
Typed configuration hierarchy for the Autonomous Navigation Module.

Sections
--------
* RobotFootprintConfig  — physical dimensions
* Nav2Config            — global/local planner parameters
* RTABMapConfig         — SLAM / localization backend
* StuckDetectorConfig   — stuck / progress monitoring
* RecoveryConfig        — recovery behavior cascade
* DockingConfig         — precision docking parameters
* BatteryRoutingConfig  — low-battery charger routing
* HumanAwareConfig      — social costmap inflation
* NavigationConfig      — top-level aggregate + ROS2 factory
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── Robot physical parameters ─────────────────────────────────────────────────


@dataclass
class RobotFootprintConfig:
    """BonBon physical geometry — used by costmap and planner."""

    radius_m: float = 0.35  # robot is circular; 35 cm radius
    max_speed_mps: float = 0.80  # hardware-enforced ceiling
    max_angular_rps: float = 1.00  # rad/s
    caution_speed_mps: float = 0.30  # when safety = CAUTION
    dock_speed_mps: float = 0.15  # during docking final approach
    height_m: float = 1.30  # for 3D collision
    base_frame: str = "base_link"
    odom_frame: str = "odom"
    map_frame: str = "map"


# ── Nav2 planner/controller parameters ───────────────────────────────────────


@dataclass
class Nav2Config:
    """Parameters forwarded to (or mirroring) nav2_params.yaml."""

    # Global planner
    global_planner: str = "NavfnPlanner"  # "NavfnPlanner" | "SmacPlanner"
    planner_tolerance_m: float = 0.5
    allow_unknown: bool = True

    # Local controller
    local_controller: str = "DWBLocalPlanner"  # "DWB" | "MPPI" | "TEB"
    controller_frequency_hz: float = 20.0

    # Costmaps
    global_costmap_update_hz: float = 1.0
    local_costmap_update_hz: float = 5.0
    local_costmap_size_m: float = 4.0  # square side length

    # Inflation
    inflation_radius_m: float = 0.55  # robot radius + 0.20 m safety margin
    cost_scaling_factor: float = 3.0

    # Action timeouts
    navigate_to_pose_timeout_sec: float = 120.0
    compute_path_timeout_sec: float = 10.0
    follow_path_timeout_sec: float = 120.0


# ── RTAB-Map ─────────────────────────────────────────────────────────────────


@dataclass
class RTABMapConfig:
    """RTAB-Map SLAM and localization settings."""

    # Mode
    mode: str = "localization"  # "slam" | "localization"
    database_path: str = "/var/lib/bonbon/rtabmap.db"

    # Topics
    rgb_topic: str = "/camera/color/image_raw"
    depth_topic: str = "/camera/depth/image_rect_raw"
    camera_info_topic: str = "/camera/color/camera_info"
    lidar_topic: str = "/scan"
    odom_topic: str = "/odom"

    # SLAM parameters
    loop_closure_threshold: float = 0.11
    rtabmap_rate_hz: float = 1.0
    map_publish_rate_hz: float = 0.5

    # AMCL fallback (if RTAB-Map unavailable)
    use_amcl_fallback: bool = True
    amcl_map_topic: str = "/map"


# ── Location registry ─────────────────────────────────────────────────────────


@dataclass
class LocationConfig:
    """Named locations that can be used as navigation goals."""

    # Each entry: name → (x, y, yaw_deg) in map frame
    named_locations: dict[str, tuple[float, float, float]] = field(
        default_factory=lambda: {
            # Café layout — matches default knowledge base in bonbon_llm
            "table_1": (2.0, 1.5, 0.0),
            "table_2": (2.0, 3.0, 0.0),
            "table_3": (2.0, 4.5, 0.0),
            "table_4": (4.0, 1.5, 180.0),
            "table_5": (4.0, 3.0, 180.0),
            "table_6": (4.0, 4.5, 180.0),
            "table_7": (6.0, 1.0, 90.0),
            "table_8": (6.0, 2.5, 90.0),
            "table_9": (6.0, 4.0, 90.0),
            "table_10": (6.0, 5.5, 90.0),
            "counter": (1.0, 0.5, 0.0),
            "entrance": (0.5, 0.0, 0.0),
            "charger_a": (0.3, 0.3, 270.0),
            "charger_b": (0.3, 1.2, 270.0),
        }
    )
    charger_ids: list[str] = field(default_factory=lambda: ["charger_a", "charger_b"])


# ── Stuck detector ───────────────────────────────────────────────────────────


@dataclass
class StuckDetectorConfig:
    """Thresholds for detecting a stuck robot."""

    enabled: bool = True
    check_rate_hz: float = 2.0

    # A robot is stuck if its displacement over the window is less than this
    min_progress_m: float = 0.05  # metres per evaluation window
    window_sec: float = 8.0  # evaluation window length

    # Velocity-based check: stuck if speed persistently near zero
    min_velocity_mps: float = 0.01
    zero_velocity_window_sec: float = 5.0

    # How many consecutive windows must fail before declaring stuck
    stuck_threshold_count: int = 2


# ── Recovery behaviors ────────────────────────────────────────────────────────


@dataclass
class RecoveryConfig:
    """Recovery behavior cascade for failed navigation."""

    enabled: bool = True
    max_retries_per_goal: int = 4

    # Ordered sequence of behaviors to attempt
    behavior_sequence: list[str] = field(
        default_factory=lambda: [
            "wait",  # 1st: wait 3 s for dynamic obstacle to clear
            "clear_costmap",  # 2nd: reset local costmap and replan
            "backup",  # 3rd: reverse 0.3 m
            "spin",  # 4th: rotate 360° to re-detect environment
            "replan",  # 5th: request fresh global plan
            "announce",  # 6th: announce via TTS asking for clearance
            "escalate",  # 7th: flag to human staff
        ]
    )

    # Per-behavior parameters
    wait_sec: float = 3.0
    backup_distance_m: float = 0.30
    backup_speed_mps: float = 0.10
    spin_angular_speed_rps: float = 0.5
    spin_full_rotations: int = 1
    announce_repeat_sec: float = 10.0


# ── Docking ──────────────────────────────────────────────────────────────────


@dataclass
class DockingConfig:
    """Precision docking / charging approach parameters."""

    enabled: bool = True
    max_dock_attempts: int = 3

    # Approach geometry
    pre_dock_distance_m: float = 0.80  # pre-dock waypoint distance from charger
    final_approach_speed_mps: float = 0.06  # very slow final approach
    max_alignment_error_m: float = 0.05  # lateral tolerance at contact
    max_heading_error_rad: float = 0.10  # ~5.7°

    # Marker detection
    use_aruco_marker: bool = True
    aruco_marker_id: int = 42
    aruco_marker_size_m: float = 0.10

    # IR beacon fallback
    use_ir_beacon: bool = True
    ir_beacon_topic: str = "/bonbon/ir_dock_signal"

    # Undocking
    undock_reverse_distance_m: float = 0.50
    undock_speed_mps: float = 0.08

    # Timeouts
    alignment_timeout_sec: float = 30.0
    final_approach_timeout_sec: float = 20.0


# ── Battery routing ───────────────────────────────────────────────────────────


@dataclass
class BatteryRoutingConfig:
    """Low-battery charger routing settings."""

    enabled: bool = True

    # Thresholds (mirror safety_params.yaml)
    low_battery_pct: float = 20.0  # start planning dock route
    critical_battery_pct: float = 10.0  # abort task, dock immediately
    resume_threshold_pct: float = 80.0  # charge level to resume tasks

    # Battery topic
    battery_topic: str = "/bonbon/battery/state"

    # If all chargers are busy, wait this long before retrying
    charger_retry_sec: float = 30.0


# ── Human-aware navigation ────────────────────────────────────────────────────


@dataclass
class HumanAwareConfig:
    """Social costmap inflation around tracked persons."""

    enabled: bool = True

    # Inflation around each tracked person
    person_inflation_radius_m: float = 0.80  # personal space buffer
    person_cost_scaling: float = 5.0  # higher → planner avoids more aggressively

    # Child/elderly get extra clearance
    vulnerable_inflation_radius_m: float = 1.20

    # Facing robot: increase clearance (person may step forward)
    facing_multiplier: float = 1.30

    # How long to keep a person in the costmap after losing track
    person_decay_sec: float = 2.0

    # Source topic
    persons_topic: str = "/perception/persons"

    # Corridor mode: announce intent before passing
    announce_passing_intent: bool = True
    announce_distance_m: float = 2.0  # announce when this close to a person


# ── Top-level config ──────────────────────────────────────────────────────────


@dataclass
class NavigationConfig:
    """Aggregate configuration for the full navigation module."""

    robot: RobotFootprintConfig = field(default_factory=RobotFootprintConfig)
    nav2: Nav2Config = field(default_factory=Nav2Config)
    rtabmap: RTABMapConfig = field(default_factory=RTABMapConfig)
    locations: LocationConfig = field(default_factory=LocationConfig)
    stuck_detector: StuckDetectorConfig = field(default_factory=StuckDetectorConfig)
    recovery: RecoveryConfig = field(default_factory=RecoveryConfig)
    docking: DockingConfig = field(default_factory=DockingConfig)
    battery_routing: BatteryRoutingConfig = field(default_factory=BatteryRoutingConfig)
    human_aware: HumanAwareConfig = field(default_factory=HumanAwareConfig)

    # Node-level
    status_publish_rate_hz: float = 5.0
    health_publish_rate_hz: float = 1.0
    map_file: str = ""  # path to .yaml map file; empty = use RTAB-Map
    use_sim_time: bool = False

    @classmethod
    def from_ros_params(cls, node) -> NavigationConfig:
        """Build config from ROS2 parameter declarations."""

        def _get(name: str, default):
            node.declare_parameter(name, default)
            return node.get_parameter(name).value

        cfg = cls()

        # Robot
        cfg.robot.max_speed_mps = _get("robot.max_speed_mps", 0.80)
        cfg.robot.radius_m = _get("robot.radius_m", 0.35)
        cfg.robot.caution_speed_mps = _get("robot.caution_speed_mps", 0.30)

        # Nav2
        cfg.nav2.global_planner = _get("nav2.global_planner", "NavfnPlanner")
        cfg.nav2.navigate_to_pose_timeout_sec = _get("nav2.timeout_sec", 120.0)
        cfg.nav2.inflation_radius_m = _get("nav2.inflation_radius_m", 0.55)

        # RTAB-Map
        cfg.rtabmap.mode = _get("rtabmap.mode", "localization")
        cfg.rtabmap.database_path = _get("rtabmap.database_path", "/var/lib/bonbon/rtabmap.db")

        # Stuck detector
        cfg.stuck_detector.enabled = _get("stuck_detector.enabled", True)
        cfg.stuck_detector.window_sec = _get("stuck_detector.window_sec", 8.0)
        cfg.stuck_detector.min_progress_m = _get("stuck_detector.min_progress_m", 0.05)

        # Recovery
        cfg.recovery.max_retries_per_goal = _get("recovery.max_retries_per_goal", 4)

        # Docking
        cfg.docking.enabled = _get("docking.enabled", True)
        cfg.docking.max_dock_attempts = _get("docking.max_dock_attempts", 3)

        # Battery routing
        cfg.battery_routing.low_battery_pct = _get("battery.low_pct", 20.0)
        cfg.battery_routing.critical_battery_pct = _get("battery.critical_pct", 10.0)

        # Human-aware
        cfg.human_aware.enabled = _get("human_aware.enabled", True)
        cfg.human_aware.person_inflation_radius_m = _get(
            "human_aware.person_inflation_radius_m", 0.80
        )

        # Node
        cfg.map_file = _get("map_file", "")
        cfg.use_sim_time = _get("use_sim_time", False)

        return cfg

    def summary(self) -> str:
        return (
            f"mode={self.rtabmap.mode} "
            f"planner={self.nav2.global_planner} "
            f"controller={self.nav2.local_controller} "
            f"stuck={self.stuck_detector.enabled} "
            f"human_aware={self.human_aware.enabled} "
            f"docking={self.docking.enabled}"
        )
