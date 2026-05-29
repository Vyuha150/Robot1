# Face emotion detection result from a single face crop
std_msgs/Header header
string event_id
builtin_interfaces/Time detected_at
string source_module
string person_id
int32 tracking_id

# Emotions with confidence [0.0..1.0]
float32 anger
float32 disgust
float32 fear
float32 happiness
float32 sadness
float32 surprise
float32 neutral

string dominant_emotion
float32 dominant_confidence
bool is_ambiguous
bool low_quality_input      # poor light, occlusion etc.
bool privacy_suppressed     # emotion suppressed by privacy gate
string privacy_level        # 'none','face_only','suppressed'
