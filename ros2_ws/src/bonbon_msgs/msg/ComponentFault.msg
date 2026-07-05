# ComponentFault.msg
# One entry in bonbon_fault_manager's live component fault registry.
# Richer than HalFault's 4-level severity: this is the CLASSIFIED,
# per-component view (bonbon_fault_manager consumes HalFault/SafetyState
# and produces this), with concrete recovery guidance per real BOM part.

uint8 OK       = 0
uint8 WARNING  = 1
uint8 DEGRADED = 2
uint8 FAULT    = 3
uint8 CRITICAL = 4
uint8 BLOCKED  = 5

std_msgs/Header header

string component_id       # e.g. "microphone", "stepper", "safety_supervisor"
string subsystem          # e.g. "audio", "vision", "actuation", "navigation", "safety", "power"
string affected_pi        # "pi1" | "pi2" | "pi3" | "shared" | "unknown"
uint8  fault_level        # one of the constants above
string error_code         # from HalFault.error_code, or a synthetic code (e.g. "DEGRADED_MODULE")
string message            # human-readable detail
string recovery_action    # concrete guidance for this component/error_code -- never generic filler
bool   dashboard_visible  # true unless internal/noise-level
builtin_interfaces/Time last_seen
uint32 occurrence_count   # monotonic count of this component's fault events since node start
