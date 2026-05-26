# ContextEvent.msg
# Published by perception_ai_node on /perception/events when a semantically
# significant scene change is detected.

std_msgs/Header header

string  event_id              # UUID
string  event_type            # "person_arrived" | "person_left" |
                              # "activity_changed" | "object_appeared" |
                              # "object_disappeared" | "interaction_started" |
                              # "interaction_ended" | "crowd_formed"
float32 confidence            # 0.0 – 1.0

# ── Subject ───────────────────────────────────────────────────────────────────
string   subject_id           # primary entity (person_id, object class, "scene")
string[] related_ids          # other involved entities

# ── Transition ────────────────────────────────────────────────────────────────
string  prior_value           # state before the change (may be empty)
string  new_value             # state after the change

string  description           # human-readable summary
