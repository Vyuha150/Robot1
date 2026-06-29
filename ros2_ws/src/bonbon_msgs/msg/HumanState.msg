# HumanState.msg
# The single fused per-person state consumed by the Behavior Engine.
# Published by bonbon_human_state_fusion on /bonbon/human/state.
#
# This message REPLACES the unused HumanStateEstimate.msg stub (which was never
# published or subscribed anywhere in the codebase).
#
# bonbon_human_state_fusion does NOT re-derive emotion from raw audio/video — it
# fuses the already-computed outputs of existing/sibling packages:
#   bonbon_multi_person_tracker  -> PersonTrack       (identity, lifecycle, location)
#   bonbon_affective_ai          -> HumanEmotionState (face+voice+text fusion)
#   bonbon_gesture                -> GestureEvent      (current gesture)
#   bonbon_speaker_intelligence  -> SpeakerTurn        (who's speaking, transcript)
# This message is the union/synthesis of those, plus identity-lifecycle and
# interaction-history fields none of them carry alone.

std_msgs/Header header
string  event_id
builtin_interfaces/Time estimated_at
string  source_module

string  person_track_id     # primary key — from bonbon_multi_person_tracker
string  known_person_id     # "" if unknown

string  lifecycle_state      # mirrors PersonTrack.lifecycle_state

# ── Speaking ──────────────────────────────────────────────────────────────────
string  active_speaker_status  # 'speaking'|'recently_spoke'|'silent'|'unknown'
string  last_transcript
float32 transcript_confidence

# ── Gesture ───────────────────────────────────────────────────────────────────
string  current_gesture
float32 gesture_confidence

# ── Emotion (from bonbon_affective_ai fusion — not re-derived here) ──────────
string  face_expression      # mirrors FaceEmotion.dominant_emotion
string  voice_emotion        # mirrors VoiceEmotion.dominant_emotion
string  text_intent          # mirrors UserIntent.intent_class
string  text_sentiment       # mirrors TextEmotion.dominant_emotion
string  emotional_state      # mirrors HumanEmotionState.dominant_state

# ── Spatial ───────────────────────────────────────────────────────────────────
geometry_msgs/Point  location_relative_to_robot
string  proximity_zone       # 'personal_space'|'social_space'|'public_space'

# ── Derived assessment ────────────────────────────────────────────────────────
float32 engagement_level     # 0.0 not engaged .. 1.0 fully engaged
float32 urgency_level        # 0.0 routine .. 1.0 emergency
float32 confidence           # overall fused-state confidence (NOT an average —
                             # see EvidenceAggregator: drops with missing modalities)

# ── Recommendations for Behavior Engine (advisory only — Behavior Engine and
#    Safety Supervisor make the actual decision; this is never acted on directly) ─
string  recommended_robot_response_style
float32 recommended_robot_distance_m
bool    requires_operator_alert

# ── Explainability ────────────────────────────────────────────────────────────
string  evidence_summary     # human-readable: which modalities contributed and why
                             # this confidence/state was reached (for the operator
                             # dashboard and for debugging fusion decisions)
