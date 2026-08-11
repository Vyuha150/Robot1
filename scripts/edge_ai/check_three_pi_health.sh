#!/usr/bin/env bash
# Edge AI Runtime brief, Phase 10. Checks the health of all three Pis
# from wherever this is run -- delegates to the two REAL, existing
# health mechanisms rather than reimplementing them:
#   1. scripts/health_check.sh          -- local module/component health
#   2. scripts/check_inter_pi_communication.py -- peer heartbeat/link state
#      (bonbon_distributed_safety's HeartbeatMonitor, see
#      docs/THREE_PI_RUNTIME_AUDIT.md)
#
# Usage:
#   scripts/edge_ai/check_three_pi_health.sh                 # local role, auto-detect
#   scripts/edge_ai/check_three_pi_health.sh --role pi2       # explicit role
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

ROLE="${2:-pi1}"
if [ "${1:-}" = "--role" ]; then
    ROLE="${2:-pi1}"
fi

echo "=== Local module health (scripts/health_check.sh) ==="
if ! bash "$ROOT_DIR/scripts/health_check.sh"; then
    echo "WARNING: local health check reported a problem (see above)" >&2
    LOCAL_OK=0
else
    LOCAL_OK=1
fi

echo ""
echo "=== Inter-Pi communication (scripts/check_inter_pi_communication.py --role $ROLE) ==="
if ! python3 "$ROOT_DIR/scripts/check_inter_pi_communication.py" --role "$ROLE"; then
    echo "WARNING: inter-Pi communication check reported a problem (see above)" >&2
    PEER_OK=0
else
    PEER_OK=1
fi

echo ""
if [ "$LOCAL_OK" = "1" ] && [ "$PEER_OK" = "1" ]; then
    echo "Three-Pi health: OK"
    exit 0
else
    echo "Three-Pi health: PROBLEMS DETECTED -- see warnings above"
    exit 1
fi
