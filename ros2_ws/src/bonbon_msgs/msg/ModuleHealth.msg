# ModuleHealth.msg
# Each ROS2 node publishes this on /bonbon/<module>/health at 1 Hz.
# The watchdog_node subscribes to all health topics to detect stale nodes.

uint8 OK       = 0
uint8 WARN     = 1
uint8 ERROR    = 2
uint8 STALE    = 3   # topic not received within expected window

std_msgs/Header header

string module_name          # e.g. "bonbon_vision.detection_node"
uint8  status               # one of the constants above
string status_text          # human-readable detail

# ── Timing ────────────────────────────────────────────────────────────────────
float32 uptime_sec
float32 last_successful_cycle_sec   # seconds since last successful work cycle

# ── Resource usage ────────────────────────────────────────────────────────────
float32 cpu_percent
float32 memory_mb
float32 latency_ms          # most recent processing latency

# ── Counters (monotonically increasing, reset on node restart) ────────────────
uint32 error_count
uint32 warning_count
uint32 processed_count      # messages/frames/requests processed
