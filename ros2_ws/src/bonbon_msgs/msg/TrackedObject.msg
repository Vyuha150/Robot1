# TrackedObject.msg
# A persistent object identity across frames, including through brief occlusion.
# Published by bonbon_object_intelligence on /bonbon/objects/tracked.
# Consumes DetectedObject (per-frame) from /bonbon/vision/objects; this message
# is the OUTPUT of permanence/calibration logic layered on top — it does not
# re-run detection.

std_msgs/Header header

string  object_track_id     # persistent ID, stable across occlusion ("obj_17")
string  class_name
float32 confidence           # calibrated confidence (see ObjectConfidenceCalibrator)

geometry_msgs/Point  position_3d     # robot base_link frame
geometry_msgs/Vector3 velocity_3d    # m/s, zero if static or unknown

builtin_interfaces/Time first_seen
builtin_interfaces/Time last_seen

# ── Permanence ────────────────────────────────────────────────────────────────
string  permanence_state    # 'visible'|'occluded'|'memory'|'lost'
                            #   visible  — detected in the current frame
                            #   occluded — not detected, but within the
                            #              occlusion-timeout grace window
                            #   memory   — beyond grace window, retained as a
                            #              low-confidence "last known" entry
                            #   lost     — expired; this is the final message
                            #              for this object_track_id
float32 occlusion_duration_sec  # 0 if visible

# ── OCR (optional — populated only for sign/document classes) ────────────────
string  ocr_text            # "" if not an OCR-eligible class or OCR disabled
float32 ocr_confidence

string  source_camera
