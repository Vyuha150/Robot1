#!/usr/bin/env bash
# Edge AI Runtime brief, Phase 11. Canonical entry point in scripts/edge_ai/
# -- delegates unchanged to scripts/ai_models/install_sherpa_onnx.sh
# (already built and verified installable this session -- sherpa-onnx
# 1.13.4, Apache-2.0, real Windows wheel confirmed) rather than a second
# copy. See docs/DUPLICATE_PIPELINE_AUDIT.md.
#
# Dry-run by default -- pass --confirm to actually install (same
# "print the plan before downloading" pattern as every install script
# in this repo).
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec bash "$ROOT_DIR/scripts/ai_models/install_sherpa_onnx.sh" "$@"
