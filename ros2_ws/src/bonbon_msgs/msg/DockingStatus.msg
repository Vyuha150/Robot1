# DockingStatus.msg
# Published by navigation_node on /navigation/docking_status during docking.

# ── Phase constants ───────────────────────────────────────────────────────────
uint8 PHASE_IDLE          = 0
uint8 PHASE_APPROACHING   = 1   # coarse navigation to charger vicinity
uint8 PHASE_ALIGNING      = 2   # precision alignment (marker / IR beacon)
uint8 PHASE_FINAL_APPROACH= 3   # slow final contact approach
uint8 PHASE_CONTACT       = 4   # contact established, charging
uint8 PHASE_FAILED        = 5   # docking failed after retries
uint8 PHASE_UNDOCKING     = 6   # reversing off the charger

std_msgs/Header  header

string   charger_id           # "charger_a" | "charger_b" etc.
uint8    phase                # PHASE_* constant
string   phase_name
float32  distance_to_dock_m   # current distance to docking point
float32  alignment_error_m    # lateral alignment error
float32  alignment_error_rad  # heading error in radians
uint8    retry_count          # docking retries so far
bool     contact_detected     # charging contact confirmed
float32  charging_current_a   # 0.0 if not yet charging
string   failure_reason       # set when phase == PHASE_FAILED
