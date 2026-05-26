# SemanticScene.msg
# Published by perception_ai_node at up to 10 Hz on /perception/scene.
# Represents a fused, high-level understanding of the current scene.

# ── Status constants ──────────────────────────────────────────────────────────
uint8 UNCERTAINTY_LOW    = 0   # all modalities fresh, high-confidence outputs
uint8 UNCERTAINTY_MEDIUM = 1   # one or more modalities stale
uint8 UNCERTAINTY_HIGH   = 2   # multiple stale modalities, outputs unreliable

# ── Activity constants ────────────────────────────────────────────────────────
uint8 ACTIVITY_IDLE        = 0
uint8 ACTIVITY_INTERACTING = 1
uint8 ACTIVITY_NAVIGATING  = 2
uint8 ACTIVITY_SERVING     = 3
uint8 ACTIVITY_CROWDED     = 4

std_msgs/Header header

string  scene_id              # UUID for this scene snapshot
float32 confidence            # overall scene-understanding confidence 0–1
uint8   uncertainty_level     # one of UNCERTAINTY_* constants above

# ── What is present ───────────────────────────────────────────────────────────
string[] present_object_classes   # deduplicated class names
string[] present_person_ids       # tracked person IDs in scene

# ── Interpretation ────────────────────────────────────────────────────────────
uint8   dominant_activity     # one of ACTIVITY_* constants above
string  activity_label        # human-readable: "idle", "interacting", …
string  spatial_context       # "open_space" | "crowded" | "near_person" | "at_station"

# ── Spatial ───────────────────────────────────────────────────────────────────
float32 human_proximity_m     # distance to nearest tracked person (-1 = none)
bool    is_crowded             # persons >= crowded_threshold

# ── Data quality ──────────────────────────────────────────────────────────────
string[] stale_modalities     # modality names with data older than stale_timeout

# ── Summary ───────────────────────────────────────────────────────────────────
string  description           # natural-language summary for logging / UI
