# RecoveryStatus.msg
# Published by navigation_node on /navigation/recovery_status during recovery.

# ── Behavior constants ────────────────────────────────────────────────────────
uint8 BEHAVIOR_NONE          = 0
uint8 BEHAVIOR_SPIN          = 1   # rotate in place to detect new paths
uint8 BEHAVIOR_BACKUP        = 2   # reverse 0.3 m
uint8 BEHAVIOR_WAIT          = 3   # pause and wait for obstacle to clear
uint8 BEHAVIOR_CLEAR_COSTMAP = 4   # clear local costmap to retry planning
uint8 BEHAVIOR_REPLAN        = 5   # request fresh global plan
uint8 BEHAVIOR_ANNOUNCE      = 6   # announce via TTS asking for clearance
uint8 BEHAVIOR_ESCALATE      = 7   # escalate to human staff

std_msgs/Header  header

string   goal_id              # goal being recovered
uint8    behavior             # active recovery behavior
string   behavior_name
uint8    attempt              # attempt number (1-indexed)
uint8    max_attempts         # configured max for current strategy
string   trigger_reason       # "stuck" | "blocked" | "plan_failed" | "timeout"
float32  recovery_elapsed_sec
bool     succeeded            # true after recovery completes successfully
string   failure_reason       # if recovery ultimately fails
