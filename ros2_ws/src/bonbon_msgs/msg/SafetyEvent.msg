# SafetyEvent.msg
# Emitted by safety_supervisor_node every time a noteworthy safety transition or
# hazard condition is detected.  QoS: RELIABLE / depth-50.
# Consumers: dashboard, sqlite_node (incident log), diagnostics_node.

# ── Event severity ────────────────────────────────────────────────────────────
uint8 INFO     = 0   # informational (state change to NORMAL / CAUTION)
uint8 WARNING  = 1   # sensor marginal, speed capped
uint8 CRITICAL = 2   # DANGER / FAULT / SAFE_STOP
uint8 RESOLVED = 3   # previously active hazard has cleared

# ── Trigger categories ────────────────────────────────────────────────────────
uint8 TRIGGER_ESTOP            = 1
uint8 TRIGGER_BUMPER           = 2
uint8 TRIGGER_CLIFF            = 3
uint8 TRIGGER_HUMAN_PROXIMITY  = 4
uint8 TRIGGER_LIDAR_FAULT      = 5
uint8 TRIGGER_CAMERA_FAULT     = 6
uint8 TRIGGER_IMU_FAULT        = 7
uint8 TRIGGER_SERVO_FAULT      = 8
uint8 TRIGGER_LOW_BATTERY      = 9
uint8 TRIGGER_OVERHEAT         = 10
uint8 TRIGGER_NAV_TIMEOUT      = 11
uint8 TRIGGER_UNSAFE_COMMAND   = 12
uint8 TRIGGER_NODE_CRASH       = 13
uint8 TRIGGER_MANUAL_RESET     = 14
uint8 TRIGGER_STARTUP          = 15

# ── Payload ───────────────────────────────────────────────────────────────────
std_msgs/Header header

uint8  severity
uint8  trigger
string trigger_name

uint8  prior_state
uint8  new_state
string prior_state_name
string new_state_name

string description              # human-readable explanation
string module_name              # module that caused the event, if applicable

# ── Sensor context snapshot (values at event time) ────────────────────────────
float32 nearest_obstacle_m      # min LIDAR range at event time (-1 = unknown)
float32 nearest_human_m         # closest tracked person (-1 = no person tracked)
float32 battery_percent         # battery level at event time (-1 = unknown)
float32 cpu_temp_c              # CPU temperature at event time (-1 = unknown)

bool    operator_notified       # dashboard alert was sent
bool    auto_recovery_attempted # watchdog tried to restart affected node
