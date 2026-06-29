# SpeakerTurn.msg
# One completed speaker turn. Published by bonbon_speaker_intelligence on
# /bonbon/speaker/turns.
#
# Consumes (does not re-run VAD/STT/diarization):
#   /speech/command            SpeechCommand   (text, confidence, per-utterance
#                                                speaker_id, doa_angle_deg)
#   bonbon_speech diarization segments (in-process, via the speech pipeline)
#   /bonbon/affective/voice_emotion  VoiceEmotion (existing bonbon_affective_ai output)
#
# This message adds what SpeechCommand cannot carry alone: a PERSISTENT
# speaker_id (stable across utterances, not reset per-utterance like the
# diarizer's raw SPEAKER_00/01 labels), and the audio-visual link to a visible
# person_track_id.

std_msgs/Header header

string  speaker_id          # persistent voice-identity ID, stable across turns
                            # ("voice_2"); independent of person_track_id
string  person_track_id     # linked visible person from bonbon_multi_person_tracker
                            # via DOA-to-bearing association; "" if speaker is
                            # off-camera or association confidence too low
float32 association_confidence  # confidence of the speaker<->person_track_id link

builtin_interfaces/Time start_time
builtin_interfaces/Time end_time

string  transcript
float32 transcript_confidence

string  voice_emotion       # mirrors VoiceEmotion.dominant_emotion
float32 emotion_confidence

float32 audio_source_direction_deg  # DOA angle; -1.0 = unknown

# ── Quality / context flags ───────────────────────────────────────────────────
bool    is_new_speaker      # first turn seen for this speaker_id this session
bool    is_overlapping      # this turn overlapped another speaker's turn
bool    is_off_camera       # speaker_id has no current person_track_id match
bool    noisy_audio
bool    short_segment
