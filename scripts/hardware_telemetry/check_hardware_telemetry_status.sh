#!/usr/bin/env bash
# Checks that hardware_telemetry_node is actually alive and publishing
# real status by echoing one message from /bonbon/hardware_telemetry/status
# with a timeout -- never assumes the node is healthy just because the
# process exists. Mirrors scripts/edge_ai/check_edge_ai_status.sh's own
# pattern.
#
# Deliberately does NOT echo /bonbon/hal/fault here: that topic only
# publishes on a real threshold-crossing event (see
# bonbon_hardware_telemetry.nodes.hardware_telemetry_node's docstring),
# so an idle, perfectly healthy robot may never publish on it -- timing
# a health check out waiting for it would report a false failure.
#
# Usage:
#   scripts/hardware_telemetry/check_hardware_telemetry_status.sh
#   scripts/hardware_telemetry/check_hardware_telemetry_status.sh --timeout 5
set -Eeuo pipefail

TIMEOUT="5"
if [ "${1:-}" = "--timeout" ]; then
    TIMEOUT="${2:-5}"
fi

TOPIC="/bonbon/hardware_telemetry/status"

printf "%-38s ... " "$TOPIC"
if timeout "$TIMEOUT" ros2 topic echo --once "$TOPIC" > /dev/null 2>&1; then
    echo "OK"
    echo ""
    echo "hardware_telemetry_node status: publishing"
    exit 0
else
    echo "NO MESSAGE (node not running, or hasn't published yet)"
    echo ""
    echo "hardware_telemetry_node status: silent -- check 'ros2 node list' for hardware_telemetry_node"
    exit 1
fi
