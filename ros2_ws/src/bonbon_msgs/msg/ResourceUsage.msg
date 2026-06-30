# ResourceUsage.msg
# System-wide CPU/memory/disk snapshot, published by bonbon_safety's
# safety_supervisor_node at ~1 Hz using the existing ResourceMonitor core
# (bonbon_safety/core/resource_monitor.py) — previously implemented and
# tested but never wired to a topic. Consumed by bonbon_perception_efficiency
# to drive load-shedding decisions; any node may subscribe for its own
# degraded-mode logic rather than re-sampling psutil itself.

std_msgs/Header header

float32 cpu_percent          # 0-100, system-wide
float32 memory_percent       # 0-100
float32 memory_mb            # this process's RSS
float32 disk_free_percent    # 0-100 free on the data partition
bool    available            # false when psutil is unavailable (sim/CI) —
                              # all fields above are zero/100 placeholders then

bool    cpu_overloaded       # cpu_percent >= 90.0
bool    memory_pressure      # memory_percent >= 85.0
bool    disk_low             # available && disk_free_percent <= 10.0

float32 recommended_load_shed  # (0.0, 1.0] processing-rate multiplier;
                                # 1.0 = full rate, lower under CPU/memory pressure
