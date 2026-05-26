# TTSRequest.msg — request speech synthesis
# Publisher: llm_orchestrator_node, safety_supervisor_node
# Subscriber: bonbon_tts/tts_node
uint8 PRIORITY_LOW    = 1
uint8 PRIORITY_NORMAL = 5
uint8 PRIORITY_HIGH   = 10   # safety announcements must use this

std_msgs/Header header
string text             # text to synthesise
uint8  priority         # higher priority preempts lower (safety uses 10)
string language         # BCP-47 language code, e.g. "en-US". Empty = default
string voice            # Piper voice model name. Empty = deployment default
float32 speed_factor    # 1.0 = normal; 1.2 = faster; 0.8 = slower
string request_id       # caller-assigned UUID for correlation with TTSStatus
