# Text-based sentiment/emotion from STT or LLM input
std_msgs/Header header
string event_id
builtin_interfaces/Time detected_at
string source_module
string person_id
int32 tracking_id
string text_snippet         # first 200 chars of analysed text

string dominant_emotion     # emergency,distress,confusion,anger,gratitude,complaint,request,medical_concern,safety_concern,neutral
float32 dominant_confidence

bool emergency_detected
bool distress_detected
bool medical_concern_detected
bool safety_concern_detected
bool anger_detected
bool confusion_detected

float32 emergency_score
float32 distress_score
float32 confusion_score
float32 anger_score
float32 gratitude_score
float32 complaint_score
float32 request_score
float32 medical_score
float32 safety_score
float32 neutral_score

string backend_used         # 'rules','transformer','mock'
bool requires_operator_alert
