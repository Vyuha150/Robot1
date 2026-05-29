# Hint for navigation/behavior about socially-aware movement
std_msgs/Header header
string event_id
builtin_interfaces/Time generated_at
string source_module

string hint_type            # 'slow_down','stop','reroute','wait','retreat','announce','maintain_distance','approach_from_front'
float32 urgency             # 0.0=low 1.0=critical
string reason               # human-readable reason
string affected_entity_id

float32 suggested_max_vel_mps
float32 suggested_distance_m
geometry_msgs/Pose suggested_pose  # suggested robot pose if applicable

bool requires_navigation_replan
bool requires_behavior_response
bool requires_tts_announcement
string suggested_tts_text
