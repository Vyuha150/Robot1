# UserIntent.msg
# Published by perception_ai_node on /perception/intent after each SpeechCommand.
# Represents the robot's best understanding of what the user wants.

std_msgs/Header header

string  intent_id             # UUID
string  speaker_id            # from SpeechCommand; "" if diarization disabled

# ── Classification ────────────────────────────────────────────────────────────
string  intent_class          # "order_item" | "navigate_to" | "ask_question" |
                              # "cancel" | "confirm" | "deny" | "help_request" |
                              # "greeting" | "silence" | "unknown"
float32 confidence            # 0.0 – 1.0

# ── Ambiguity ─────────────────────────────────────────────────────────────────
bool    is_ambiguous          # true = confidence < threshold or conflicting
string  fallback_response     # suggested robot utterance when is_ambiguous=true

# ── Slots (parallel arrays, equal length) ────────────────────────────────────
string[] slot_names           # e.g. ["item",   "quantity"]
string[] slot_values          # e.g. ["coffee", "two"]
float32[] slot_confidences    # per-slot confidence

# ── Source ────────────────────────────────────────────────────────────────────
string  raw_text              # original transcribed text (may be empty for silence)
float32 speech_confidence     # confidence of the underlying SpeechCommand
