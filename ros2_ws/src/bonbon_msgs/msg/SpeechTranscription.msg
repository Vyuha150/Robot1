# SpeechTranscription.msg
# Detailed per-segment transcription result (richer than SpeechCommand).
# Published alongside SpeechCommand for downstream logging / analytics.

std_msgs/Header header

string  text
string  language
float32 confidence

# ── Per-word detail (populated when Whisper returns word timestamps) ───────────
string[]  words
float32[] word_start_times_sec  # offset from audio_start
float32[] word_end_times_sec
float32[] word_confidences      # per-word confidence

# ── Speaker diarization ───────────────────────────────────────────────────────
string  speaker_id              # primary speaker for this utterance
string[] all_speaker_ids        # all speakers if multiple voices detected

# ── Audio ─────────────────────────────────────────────────────────────────────
float32 audio_duration_sec
float32 transcription_ms
float32 doa_angle_deg
bool    vad_force_cut           # true when speech cut due to max_duration
