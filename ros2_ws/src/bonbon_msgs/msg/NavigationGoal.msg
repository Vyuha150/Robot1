# NavigationGoal.msg
# Published by navigation_node on /navigation/goal when a new goal is accepted.

# ── Goal type constants ───────────────────────────────────────────────────────
uint8 TYPE_WAYPOINT  = 0   # absolute map-frame pose
uint8 TYPE_NAMED     = 1   # named location from location registry
uint8 TYPE_CHARGER   = 2   # docking station approach
uint8 TYPE_PERSON    = 3   # approach a tracked person

# ── Priority ──────────────────────────────────────────────────────────────────
uint8 PRIORITY_LOW    = 0
uint8 PRIORITY_NORMAL = 1
uint8 PRIORITY_HIGH   = 2
uint8 PRIORITY_URGENT = 3

std_msgs/Header  header

string           goal_id           # UUID for tracking
uint8            goal_type         # one of TYPE_* above
uint8            priority

# ── Target ────────────────────────────────────────────────────────────────────
geometry_msgs/PoseStamped  target_pose   # map frame
string                     named_location  # e.g. "table_3", "counter", "charger_a"
string                     person_id       # track_id if TYPE_PERSON

# ── Constraints ───────────────────────────────────────────────────────────────
float32  timeout_sec          # 0 = use default (120 s)
float32  arrival_tolerance_m  # distance tolerance for arrival (default 0.3 m)
bool     require_precise_dock # true = use docking controller instead of Nav2

# ── Source ────────────────────────────────────────────────────────────────────
string   requester_id         # "llm_orchestrator" | "safety" | "operator"
string   recommendation_id    # UUID from BehaviorRecommendation that triggered this
