#!/usr/bin/env bash
# Edge AI Runtime brief, Phase 11. Canonical entry point in scripts/edge_ai/
# -- delegates unchanged to scripts/ai_models/download_qwen25_05b.sh
# (already built, already verified on real Pi-2 hardware 2026-07-06, see
# docs/PI2_QWEN25_05B_SETUP_REPORT.md) rather than a second copy. See
# docs/DUPLICATE_PIPELINE_AUDIT.md.
#
# qwen2.5:0.5b is the ONLY local LLM this repo auto-downloads --
# llama3.2:1b and qwen2.5:1.5b are benchmark-only candidates and are
# never pulled without explicit approval (see
# config/models/model_registry.yaml's enabled_by_default flags).
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec bash "$ROOT_DIR/scripts/ai_models/download_qwen25_05b.sh" "$@"
