# PersonTrack.msg
# A person's identity-lifecycle record. Published by bonbon_multi_person_tracker
# on /bonbon/persons/tracks.
#
# This is the SINGLE SOURCE OF TRUTH for "who is in the scene and what is their
# lifecycle state" — every other perception package (gesture, speaker_intelligence,
# human_state_fusion) keys its output to person_track_id from this message rather
# than re-deriving identity.
#
# Consumes (does not redetect):
#   /bonbon/vision/persons          PersonStateArray  (track_id, face_id, position)
# PersonState.track_id is a raw per-frame/per-session detector ID that resets on
# any track loss; person_track_id here is stable ACROSS a temporarily_lost gap.

std_msgs/Header header

string  person_track_id     # stable for the life of this person in the scene,
                            # survives temporarily_lost -> reappeared
string  temporary_person_id # human-friendly anonymous label ("Person_3"), stable
                            # alongside person_track_id; used before any identity
                            # is known and kept for privacy-mode display
string  known_person_id     # registered/known identity; "" if unknown

string  raw_track_id        # bonbon_vision's PersonState.track_id THIS CYCLE
                            # ("person_3") — bridges to packages that still key
                            # off vision's raw per-frame ID (e.g. HumanEmotionState
                            # from bonbon_affective_ai, predates person_track_id).
                            # "" while temporarily_lost (the raw ID is not
                            # trustworthy once the underlying detection is gone).

# ── Visual evidence ───────────────────────────────────────────────────────────
int32   bbox_x
int32   bbox_y
int32   bbox_w
int32   bbox_h
bool    face_bbox_available
int32   face_bbox_x
int32   face_bbox_y
int32   face_bbox_w
int32   face_bbox_h

string  body_embedding_id   # reference to a stored body re-id embedding; "" if none
string  face_embedding_id   # reference to a stored face embedding; "" if none

# ── Spatial state ─────────────────────────────────────────────────────────────
geometry_msgs/Point  position_3d
geometry_msgs/Vector3 velocity_3d

# ── Lifecycle ─────────────────────────────────────────────────────────────────
string  lifecycle_state
    # 'new_candidate'      — seen < confirmation window, not yet confirmed
    # 'present'            — confirmed, in current frame
    # 'active_interaction' — present AND currently speaking/gesturing/addressed
    # 'temporarily_lost'   — missed frames within the loss-grace window
    # 'reappeared'         — re-matched after temporarily_lost (one-shot transition)
    # 'left_scene'         — grace window expired; this is the final message
                            #   for this person_track_id

builtin_interfaces/Time first_seen
builtin_interfaces/Time last_seen
float32 time_since_last_seen_sec

float32 confidence          # identity-continuity confidence, 0.0-1.0
