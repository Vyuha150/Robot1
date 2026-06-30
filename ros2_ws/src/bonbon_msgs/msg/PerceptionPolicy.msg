# PerceptionPolicy.msg
# Recommended confidence thresholds per signal, published by
# bonbon_perception_efficiency on /bonbon/perception_efficiency/policy.
#
# Advisory only — no package currently has a live-reconfigure path to apply
# this automatically. Consumers (dashboards, or future dynamic-reconfigure
# integrations) read this; it never overrides a package's own configured
# minimum threshold (see ConfidencePolicyManager).

std_msgs/Header header

string[]  signal_names           # e.g. "gesture","face","voice","text","object"
float32[] recommended_thresholds # parallel array, same length as signal_names
string[]  reasons                # parallel array — why this value was recommended

bool      degraded_mode_active
bool      safety_elevated
