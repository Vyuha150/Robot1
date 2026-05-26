# PersonState.msg — state of a single tracked person
string  track_id            # persistent per-session ID (e.g. "person_3")
string  face_id             # registered user ID, empty if unknown
float32 distance_m          # distance from robot base_link (metres)
float32 bearing_deg         # bearing from robot forward axis (-180 to 180)
float32 velocity_mps        # estimated walking speed (0 if stationary)
bool    facing_robot        # gaze / body orientation toward robot
string  age_group           # "child" | "adult" | "elderly" | "unknown"
geometry_msgs/Point position  # 3D position in map frame
