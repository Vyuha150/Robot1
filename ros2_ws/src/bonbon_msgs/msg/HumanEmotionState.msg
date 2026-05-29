# Fused multi-modal human emotional state estimate
std_msgs/Header header
string event_id
builtin_interfaces/Time estimated_at
string source_module
string person_id
int32 tracking_id

# Dominant state
string dominant_state       # neutral,happy,confused,frustrated,angry,distressed,fearful,urgent,tired,engaged,disengaged
float32 dominant_confidence
bool is_stable              # consistent across recent frames

# Evidence breakdown
float32 face_contribution
float32 voice_contribution
float32 text_contribution
float32 gesture_contribution
bool face_available
bool voice_available
bool text_available
bool gesture_available

# Recommendations for behavior engine
string recommended_response_style  # normal,cheerful,calm_supportive,concise,apologetic,emergency_clear,child_friendly,elderly_friendly
float32 recommended_distance_m
bool requires_operator_alert
string suggested_tts_emotion       # maps to bonbon_tts emotion parameter
float32 interaction_patience_multiplier  # 1.0=normal 2.0=needs more time

# History
int32 state_duration_sec
int32 state_change_count_last_60s
string previous_state
