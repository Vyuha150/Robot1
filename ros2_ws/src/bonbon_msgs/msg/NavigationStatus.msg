# NavigationStatus.msg
# Published by navigation_node on /navigation/status at 5 Hz.

# ── State constants ───────────────────────────────────────────────────────────
uint8 STATE_IDLE           = 0   # no active goal
uint8 STATE_PLANNING       = 1   # computing path
uint8 STATE_EXECUTING      = 2   # following path
uint8 STATE_RECOVERING     = 3   # executing recovery behavior
uint8 STATE_DOCKING        = 4   # precision dock approach
uint8 STATE_ARRIVED        = 5   # goal reached
uint8 STATE_BLOCKED        = 6   # obstacle blocking, waiting
uint8 STATE_FAILED         = 7   # goal failed (unreachable / timeout)
uint8 STATE_CANCELLED      = 8   # goal cancelled by request
uint8 STATE_SAFETY_STOPPED = 9   # halted by safety supervisor

# ── Result codes ──────────────────────────────────────────────────────────────
uint8 RESULT_NONE         = 0
uint8 RESULT_SUCCESS      = 1
uint8 RESULT_TIMEOUT      = 2
uint8 RESULT_UNREACHABLE  = 3
uint8 RESULT_STUCK        = 4
uint8 RESULT_SAFETY_STOP  = 5
uint8 RESULT_CANCELLED    = 6
uint8 RESULT_PLAN_FAILED  = 7

std_msgs/Header  header

# ── Active goal ───────────────────────────────────────────────────────────────
string  active_goal_id      # UUID of active NavigationGoal; empty if idle
uint8   state               # current navigation state
string  state_name          # human-readable state label
string  status_text         # detail text (recovery type, failure reason, etc.)
uint8   result_code         # last result code (RESULT_* constants)

# ── Progress ──────────────────────────────────────────────────────────────────
float32 distance_remaining_m    # distance to goal (m), -1 if unknown
float32 progress_pct            # 0–100 % path completion
float32 elapsed_sec             # seconds since goal accepted
float32 eta_sec                 # estimated seconds to arrival, -1 if unknown

# ── Robot state ───────────────────────────────────────────────────────────────
geometry_msgs/PoseStamped  current_pose   # latest estimated pose (map frame)
float32 linear_velocity_mps              # current forward speed
float32 angular_velocity_rps             # current angular speed

# ── Recovery ─────────────────────────────────────────────────────────────────
string  recovery_behavior    # name of active recovery; empty if not recovering
uint8   recovery_attempt     # how many recoveries attempted for current goal

# ── Queue ─────────────────────────────────────────────────────────────────────
uint8   goals_queued         # number of goals waiting behind current goal
