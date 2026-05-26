# BehaviorRecommendation.msg
# Published by perception_ai_node on /perception/behavior whenever the AI
# determines a new robot behavior is appropriate.

# ── Priority constants ────────────────────────────────────────────────────────
uint8 PRIORITY_LOW    = 0
uint8 PRIORITY_NORMAL = 1
uint8 PRIORITY_HIGH   = 2
uint8 PRIORITY_URGENT = 3

std_msgs/Header header

string  recommendation_id     # UUID

# ── What to do ────────────────────────────────────────────────────────────────
string  behavior_class        # "idle" | "approach_person" | "speak_greeting" |
                              # "speak_clarification" | "speak_response" |
                              # "navigate_to_goal" | "stop_navigation" |
                              # "alert_safety" | "wait_for_input" | "serve_item"
float32 confidence            # 0.0 – 1.0
uint8   priority              # one of PRIORITY_* above

# ── Trigger ───────────────────────────────────────────────────────────────────
string  trigger_type          # "user_intent" | "risk_event" | "context_event" | "periodic"
string  trigger_id            # UUID of the triggering message

# ── Parameterisation (parallel arrays) ───────────────────────────────────────
string[] param_names          # e.g. ["target_id", "speech_text", "goal_x"]
string[] param_values         # corresponding values

float32 timeout_sec           # how long this recommendation stays valid; 0 = no expiry
