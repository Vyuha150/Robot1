#!/usr/bin/env bash
# Run the Phase-4 production scenario suite and write a JUnit XML report
# the dashboard's /validation/test-results endpoint reads.
#
#   scripts/run_production_tests.sh           CI-safe only (skips hardware_gated)
#   scripts/run_production_tests.sh --all      include hardware_gated (SKIPs off-Pi)
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OUT_DIR="devops/project-status"
mkdir -p "$OUT_DIR"

MARKER_ARGS=(-m "not hardware_gated")
if [[ "${1:-}" == "--all" ]]; then
  MARKER_ARGS=()
fi

python -m pytest tests/production "${MARKER_ARGS[@]}" \
  --junitxml="$OUT_DIR/production_test_results.xml" \
  -q -p no:cacheprovider

echo "Wrote $OUT_DIR/production_test_results.xml"
