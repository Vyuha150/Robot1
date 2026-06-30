# PerceptionBudget.msg
# Consolidated per-cycle perception resource budget, published by
# bonbon_perception_efficiency on /bonbon/perception_efficiency/budget.
# Advisory — see PerceptionPolicy.msg for the same caveat.

std_msgs/Header header

# ── Load shedding ──────────────────────────────────────────────────────────────
string  load_level          # 'normal'|'reduced'|'minimal'|'critical'
float32 load_scale          # (0.0,1.0] processing-rate multiplier
string  load_reason

# ── Frame sampling recommendations (parallel arrays) ────────────────────────────
string[] sample_consumers          # e.g. "vision","gesture"
int32[]  sample_every_n_frames     # recommended: process every Nth frame
string[] sample_reasons

# ── Active-person focus weights (parallel arrays) ───────────────────────────────
string[]  focus_person_track_ids
float32[] focus_weights            # 1.0=full processing .. ~0.3=background
string[]  focus_reasons

string  current_focus_person_track_id  # "" if nobody is currently the focus
