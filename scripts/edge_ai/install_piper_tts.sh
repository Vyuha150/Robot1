#!/usr/bin/env bash
# Edge AI Runtime brief, Phase 11. Canonical entry point in scripts/edge_ai/
# -- delegates unchanged to scripts/ai_models/install_piper_tts.sh
# (already built and verified this session -- piper-tts 1.6.0 + the real
# en_US-lessac-medium voice, real synthesis confirmed working end-to-end)
# rather than a second copy. See docs/DUPLICATE_PIPELINE_AUDIT.md.
#
# Pass --with-hindi to also fetch the unbenchmarked Hindi candidate
# voice (GAP-8, still open -- no Telugu voice exists in piper-voices at
# all as of this pass).
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec bash "$ROOT_DIR/scripts/ai_models/install_piper_tts.sh" "$@"
