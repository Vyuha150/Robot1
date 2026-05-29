# Status of an actuation gesture execution
std_msgs/Header header
string event_id             # matches ActuationGesture.event_id
builtin_interfaces/Time updated_at
string source_module

string gesture_name
string status               # 'queued','executing','completed','cancelled','failed','timeout','safety_blocked'
float32 progress_pct        # 0.0..100.0
string failure_reason       # populated on failure/safety_blocked
bool safety_blocked

# Current joint states (simplified)
float32 head_pan_rad
float32 head_tilt_rad

int32 queue_depth
