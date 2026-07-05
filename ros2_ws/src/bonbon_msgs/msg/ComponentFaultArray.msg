# ComponentFaultArray.msg
# Full snapshot of bonbon_fault_manager's component fault registry,
# published TRANSIENT_LOCAL so a late-joining dashboard client gets
# current state immediately (matching SafetyState.msg's convention).

std_msgs/Header header
ComponentFault[] components
uint8 worst_level   # max(fault_level) across all components -- quick dashboard badge
