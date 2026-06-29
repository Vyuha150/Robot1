# A recognised gesture from a person
std_msgs/Header header
string event_id
builtin_interfaces/Time detected_at
string source_module
string person_id            # known-identity ID; "" if unknown
int32 tracking_id           # legacy per-frame track index (kept for back-compat)
string person_track_id      # bonbon_multi_person_tracker lifecycle ID — PREFER THIS
                            # for any new consumer; "" only if the tracker is offline

string gesture_type         # wave,raised_hand,stop_palm,pointing_left,pointing_right,pointing_forward,come_here,go_away,thumbs_up,thumbs_down,head_nod_yes,head_shake_no,fallen_or_bent_posture,unknown
float32 confidence

# Which limb/body-part produced the gesture
string hand_side            # 'left'|'right'|'both'|'' (not hand-based)
string body_part            # 'hand'|'arm'|'head'|'posture'

# Mapped robot-facing meaning
string recommended_intent   # e.g. 'stop_robot','greet','request_attention','indicate_direction'

# Spatial context
geometry_msgs/Point person_position_map  # in map frame
geometry_msgs/Vector3 pointing_direction # for pointing gestures

# Safety classification
bool safety_relevant
string safety_class         # 'stop','alert','approach','retreat','unknown','none'
bool requires_immediate_response

# Temporal context — confirms this gesture is not a one-frame false positive
float32 gesture_duration_sec
float32 temporal_stability  # 0.0–1.0, fraction of the smoothing window agreeing
bool is_held                # gesture is still being held
bool just_started
bool just_ended

string backend_used         # 'mediapipe','yolo_pose','mock'
