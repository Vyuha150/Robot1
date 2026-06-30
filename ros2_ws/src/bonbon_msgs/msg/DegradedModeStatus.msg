# DegradedModeStatus.msg
# System-wide perception degraded mode, published by
# bonbon_perception_efficiency on /bonbon/perception_efficiency/degraded_mode.
# Distinct from each package's own internal degraded flag (e.g.
# DetectedObjectArray.is_degraded) — this reflects SUSTAINED system-wide
# pressure or a safety FAULT/SAFE_STOP, not any single package's local state.

std_msgs/Header header

bool    is_degraded
string  reason
float32 duration_sec        # time spent in the current degraded state; 0 if not degraded
