# Spatial relationship between two entities
std_msgs/Header header
string event_id
builtin_interfaces/Time computed_at
string source_module

string entity_a_id
string entity_b_id
string relation_type        # 'near','far','blocking','approaching','retreating','facing','behind','side_by_side'
float32 distance_m
float32 bearing_deg         # bearing from A to B
bool is_violating_personal_space
bool is_blocking_path
bool is_in_restricted_zone
float32 confidence
