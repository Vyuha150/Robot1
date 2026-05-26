# SpeechCommand.msg
# Published by speech_node when a complete utterance is transcribed.
# Consumed by the dialogue / task planner.

std_msgs/Header header

# ── Transcription ──────────────────────────────────────────────────────────────
string  text                    # full transcribed text (empty if fallback)
string  language                # ISO 639-1 code detected or forced ("en", "zh", …)
float32 confidence              # 0.0 – 1.0   (1 = perfect)

# ── Quality flags ─────────────────────────────────────────────────────────────
bool    is_low_confidence       # true when confidence < configured threshold
bool    is_timeout              # true when STT timed out — text is empty
bool    is_silence              # true when VAD got audio but STT returned empty text
bool    wake_word_triggered     # true when command followed a confirmed wake word

# ── Speaker ───────────────────────────────────────────────────────────────────
string  speaker_id              # "" if diarization disabled or privacy_mode=true

# ── Audio metadata ────────────────────────────────────────────────────────────
float32 audio_duration_sec      # length of the speech segment fed to STT
float32 transcription_ms        # wall-clock STT latency
float32 doa_angle_deg           # direction-of-arrival from HAL mic; -1.0 = unknown
