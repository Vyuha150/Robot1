# SafetyState.msg
# Published by safety_supervisor_node at 10 Hz on /bonbon/safety/state
# QoS: RELIABLE / TRANSIENT_LOCAL so late-joining nodes receive the last state.

# ── State constants ───────────────────────────────────────────────────────────
uint8 INITIALIZING = 0   # startup — awaiting sensor confirmation
uint8 NORMAL       = 1   # all systems nominal, full capability
uint8 CAUTION      = 2   # human nearby or sensor marginal, speed capped 0.3 m/s
uint8 DANGER       = 3   # imminent hazard, all motion stopped
uint8 DOCKING      = 4   # low battery, navigating to charger at ≤ 0.2 m/s
uint8 DEGRADED     = 5   # non-critical module offline, partial capability
uint8 FAULT        = 6   # hardware fault, manual reset required
uint8 SAFE_STOP    = 7   # hardware e-stop engaged, motor power cut

# ── Payload ───────────────────────────────────────────────────────────────────
std_msgs/Header header

uint8  state                      # one of the constants above
string state_name                 # human-readable state label
string reason                     # why we entered this state (for logs/UI)
float32 time_in_state_sec         # seconds since last transition

# ── Capability flags (derived from state, pre-computed for consumers) ─────────
bool   actuation_permitted        # servos and wheels may receive commands
bool   navigation_permitted       # nav2 goal acceptance is allowed
float32 max_velocity_mps          # safety gate enforces this upper bound

# ── Degraded-module tracking ──────────────────────────────────────────────────
string[] degraded_modules         # list of module names currently in degraded class
bool   requires_manual_reset      # true when FAULT or SAFE_STOP
