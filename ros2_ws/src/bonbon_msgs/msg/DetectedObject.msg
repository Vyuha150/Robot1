# DetectedObject.msg
# A single object detection result from the vision pipeline.
# Published inside DetectedObjectArray on /bonbon/vision/objects.

# ── Class identity ────────────────────────────────────────────────────────────
int32   class_id          # COCO class index (0 = person, 56 = chair, …)
string  class_name        # human-readable label ("person", "chair", "door", …)
float32 confidence         # detector confidence 0.0–1.0

# ── Bounding box (image pixels, top-left origin) ──────────────────────────────
int32   bbox_x
int32   bbox_y
int32   bbox_w
int32   bbox_h

# ── 3-D robot-relative pose ───────────────────────────────────────────────────
float32 depth_m           # distance along camera Z axis (NaN if unknown)
float32 bearing_deg       # horizontal bearing from robot forward axis
geometry_msgs/Point position_3d  # fused XYZ in robot base_link frame; NaN if unknown

# ── Tracking ──────────────────────────────────────────────────────────────────
string  track_id          # persistent ID within session; "" if not tracked
string  tracking_status   # "new"|"tracked"|"occluded"|"lost"|"untracked"

# ── Segmentation (optional) ────────────────────────────────────────────────────
string  mask_id           # reference to a segmentation mask asset; "" if none

# ── Source ────────────────────────────────────────────────────────────────────
string  source_camera     # which camera produced this detection ("front", "mock", …)

# ── Privacy ───────────────────────────────────────────────────────────────────
bool    is_anonymized     # true = face/identity blurred in annotated image
