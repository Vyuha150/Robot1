# High-level actuation gesture request
std_msgs/Header header
string event_id
builtin_interfaces/Time requested_at
string source_module
string person_id
int32 tracking_id

string gesture_name         # look_at_person,look_at_object,nod_yes,shake_no,wave,point_left,point_right,point_forward,stop_gesture,invite_gesture,handover_pose,rest_pose,safe_folded_pose,listening_pose,thinking_pose,greeting_pose,apology_pose,emergency_attention_pose,idle_scan,turn_toward_person,slight_retreat
string target_frame_id      # tf2 frame to target for look_at gestures
geometry_msgs/Point target_point  # world point for directional gestures

int32 priority              # 0=low 5=normal 10=high 20=emergency
float32 speed_scale         # 0.1=very slow 1.0=normal speed
bool interruptible          # can be cancelled mid-execution
float32 timeout_sec
