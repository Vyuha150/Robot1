# Voice / tone-of-voice emotion from audio segment
std_msgs/Header header
string event_id
builtin_interfaces/Time detected_at
string source_module
string person_id
int32 tracking_id
float32 segment_duration_sec

string dominant_emotion     # neutral,happy,sad,angry,fearful,stressed,calm,urgent,confused
float32 dominant_confidence

float32 arousal             # 0.0=calm 1.0=excited (if model supports)
float32 valence             # 0.0=negative 1.0=positive (if model supports)
bool arousal_valid
bool valence_valid

float32 neutral_score
float32 happy_score
float32 sad_score
float32 angry_score
float32 fearful_score
float32 stressed_score
float32 calm_score
float32 urgent_score
float32 confused_score

bool noisy_audio
bool silence_detected
bool short_segment
bool model_failed
string backend_used
