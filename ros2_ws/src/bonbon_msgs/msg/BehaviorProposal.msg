# A behavior proposed by LLM, speech, or rule system — not yet validated
std_msgs/Header header
string event_id
builtin_interfaces/Time proposed_at
string source_module        # 'llm','speech_intent','gesture','rule_engine','operator'
string person_id
int32 tracking_id

string proposal_type        # 'speak','navigate','gesture','approach','retreat','dock','alert_operator','ask_clarification','ignore','pause','resume'
string proposal_content     # tts text, nav goal id, gesture name, etc.
float32 urgency             # 0.0=low 1.0=critical
string justification        # why this behavior is proposed

# Navigation sub-fields (populated when type=navigate/approach/retreat)
geometry_msgs/Pose nav_goal_pose
string nav_goal_label

# TTS sub-fields (populated when type=speak)
string tts_text
string tts_emotion
string tts_language

# Gesture sub-fields
string gesture_name

bool safety_check_required
string raw_llm_command      # original LLM command if from LLM
