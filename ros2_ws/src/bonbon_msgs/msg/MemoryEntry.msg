# MemoryEntry.msg
# Published by perception_ai_node on /perception/memory_updates to notify
# other nodes that a memory record has been created or updated.

std_msgs/Header header

string  entry_id              # UUID
string  entry_type            # "person_seen" | "person_interaction" |
                              # "scene_recorded" | "object_noted" |
                              # "preference_stored" | "person_forgotten"
string  subject_id            # the primary entity this entry is about

# ── Content (key-value pairs, parallel arrays) ────────────────────────────────
string[] key_names
string[] key_values

float32 relevance_score       # how important this memory is (0–1)
bool    is_private            # handle per privacy policy (redact in logs/UI)
float32 expires_at_sec        # epoch time; 0 = no expiry
