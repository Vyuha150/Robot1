#!/usr/bin/env bash
# Single entry point to select the BonBon deployment mode and guarantee
# exactly one safety supervisor. Dispatches to the mode-specific enable
# scripts, which disable the conflicting set before enabling the chosen one.
#
#   sudo bash scripts/select_deployment_mode.sh monolithic
#   sudo bash scripts/select_deployment_mode.sh modular_pi
#   bash scripts/select_deployment_mode.sh status     # validate only, no change
#
# Run on the host, as root for monolithic/modular_pi.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-}"

usage() {
  echo "Usage: $0 {monolithic|modular_pi|status}" >&2
  echo "  monolithic  — MODE A: bonbon-core runs the whole stack (sim/dev/lab)" >&2
  echo "  modular_pi  — MODE B: per-subsystem services (Raspberry Pi production)" >&2
  echo "  status      — validate the current topology, change nothing" >&2
}

case "$MODE" in
  monolithic)
    exec bash "${ROOT}/scripts/enable_monolithic_mode.sh"
    ;;
  modular_pi)
    exec bash "${ROOT}/scripts/enable_modular_pi_mode.sh"
    ;;
  status)
    exec python3 "${ROOT}/scripts/validate_boot_topology.py" --check-running-nodes
    ;;
  ""|-h|--help)
    usage
    exit 1
    ;;
  *)
    echo "[FAIL] unknown mode: '$MODE'" >&2
    usage
    exit 1
    ;;
esac
