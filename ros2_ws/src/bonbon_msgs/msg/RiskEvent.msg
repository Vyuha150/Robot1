# RiskEvent.msg
# Published by perception_ai_node on /perception/risks when a safety-relevant
# situation is detected by the AI risk assessor.
# QoS: RELIABLE / depth-50 — consumers must not miss risk events.

# ── Severity constants ────────────────────────────────────────────────────────
uint8 SEVERITY_INFO     = 0
uint8 SEVERITY_LOW      = 1
uint8 SEVERITY_MEDIUM   = 2
uint8 SEVERITY_HIGH     = 3
uint8 SEVERITY_CRITICAL = 4

std_msgs/Header header

string  risk_id               # UUID
uint8   severity              # one of SEVERITY_* above
string  severity_label        # human-readable: "info", "low", …

# ── Classification ────────────────────────────────────────────────────────────
string  risk_type             # "person_too_close" | "person_nearby" |
                              # "collision_risk" | "crowded_area" |
                              # "unknown_person" | "navigation_with_uncertainty" |
                              # "conflicting_commands" | "stale_sensors"
float32 confidence            # 0.0 – 1.0

# ── Context ───────────────────────────────────────────────────────────────────
string  subject_id            # entity that triggered the risk (person_id, "scene")
float32 distance_m            # relevant distance (-1 if not spatial)

string  description           # human-readable explanation

# ── Action ────────────────────────────────────────────────────────────────────
bool    requires_immediate_action   # true = safety_supervisor should act now
string  suggested_action            # e.g. "stop", "slow_down", "notify_operator"
