# A tracked entity (person, object, robot) in world space
std_msgs/Header header
string event_id
builtin_interfaces/Time observed_at
string source_module
string entity_id
string entity_type          # 'person','object','robot','unknown'
string person_id            # populated for persons
int32 tracking_id

geometry_msgs/PoseStamped pose
geometry_msgs/Vector3 velocity_mps
geometry_msgs/Vector3 dimensions_m  # bounding box w,d,h

string zone_id              # which semantic zone the entity is in
bool is_static
bool is_occluded
float32 confidence
float32 time_since_last_obs_sec

# Person-specific
string person_category      # 'adult','child','elderly','wheelchair','staff','unknown'
bool is_approaching_robot
bool is_moving_away
float32 approach_speed_mps
