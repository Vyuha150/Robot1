# PerceptionEfficiencyMetrics.msg
# Aggregated perception-layer metrics, published by
# bonbon_perception_efficiency on /bonbon/perception_efficiency/metrics.
# Aggregates the ModuleHealth every perception node already publishes —
# does not add a second metrics-collection pipeline.

std_msgs/Header header

int32   module_count
int32   worst_status            # mirrors ModuleHealth status constants (0=OK..3=STALE)
string  worst_status_module
float32 avg_latency_ms
float32 max_latency_ms
int32   total_errors
int32   total_processed

# Resource snapshot, mirrored from the latest ResourceUsage for convenience
# (so a dashboard need only subscribe one topic for the full picture).
float32 cpu_percent
float32 memory_percent
float32 recommended_load_shed

string  load_level
bool    degraded_mode_active
