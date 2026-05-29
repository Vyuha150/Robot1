# A recognised gesture from a person
std_msgs/Header header
string event_id
builtin_interfaces/Time detected_at
string source_module
string person_id
int32 tracking_id

string gesture_type         # wave,raised_hand,stop_palm,pointing_left,pointing_right,pointing_forward,thumbs_up,thumbs_down,come_here,go_away,head_nod_yes,head_shake_no,fallen_posture,unknown
float32 confidence

# Spatial context
geometry_msgs/Point person_position_map  # in map frame
geometry_msgs/Vector3 pointing_direction # for pointing gestures

# Safety classification
bool safety_relevant
string safety_class         # 'stop','alert','approach','retreat','unknown','none'
bool requires_immediate_response

# Temporal context
float32 gesture_duration_sec
bool is_held                # gesture is still being held
bool just_started
bool just_ended

string backend_used         # 'mediapipe','yolo_pose','mock'
