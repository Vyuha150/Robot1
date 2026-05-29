# Combined estimate of a human's full state for behavior planning
std_msgs/Header header
string event_id
builtin_interfaces/Time estimated_at
string source_module
string person_id
int32 tracking_id

# Identity & classification
string person_category      # adult,child,elderly,wheelchair,staff,unknown
bool identity_known
string name_if_known

# Emotional state (from affective AI)
string emotional_state
float32 emotional_confidence

# Spatial state (from spatial module)
geometry_msgs/PoseStamped pose
float32 distance_to_robot_m
string proximity_zone       # personal_space(<1m),social_space(1-3m),public_space(>3m)
bool is_facing_robot
bool is_moving
float32 movement_speed_mps

# Intent signals
string last_gesture
string last_speech_intent
float32 engagement_level    # 0.0=not engaged 1.0=fully engaged

# Safety flags
bool requires_special_care  # child, elderly, wheelchair
bool requires_operator_alert
bool is_in_distress
