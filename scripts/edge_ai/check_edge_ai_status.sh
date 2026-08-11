#!/usr/bin/env bash
# Edge AI Runtime brief, Phase 10/12. Checks that edge_ai_runtime_node
# (Pi-2) is actually alive and publishing real status by echoing one
# message from each of its 6 topics with a timeout -- never assumes
# the node is healthy just because the process exists.
#
# Usage:
#   scripts/edge_ai/check_edge_ai_status.sh
#   scripts/edge_ai/check_edge_ai_status.sh --timeout 5
set -Eeuo pipefail

TIMEOUT="5"
if [ "${1:-}" = "--timeout" ]; then
    TIMEOUT="${2:-5}"
fi

TOPICS=(
    "/bonbon/edge_ai/status"
    "/bonbon/edge_ai/models"
    "/bonbon/edge_ai/routes"
    "/bonbon/edge_ai/resources"
    "/bonbon/edge_ai/safety"
    "/bonbon/edge_ai/cache"
)

FAILED=0
for topic in "${TOPICS[@]}"; do
    printf "%-32s ... " "$topic"
    if timeout "$TIMEOUT" ros2 topic echo --once "$topic" > /dev/null 2>&1; then
        echo "OK"
    else
        echo "NO MESSAGE (node not running, or hasn't published yet)"
        FAILED=1
    fi
done

echo ""
if [ "$FAILED" = "0" ]; then
    echo "edge_ai_runtime_node status: all 6 topics publishing"
    exit 0
else
    echo "edge_ai_runtime_node status: one or more topics silent -- check 'ros2 node list' for edge_ai_runtime_node"
    exit 1
fi
