#!/bin/bash
# scripts/ai_models/install_sherpa_onnx.sh
#
# Installs the sherpa-onnx package (Apache-2.0) for benchmark comparison
# against the already-deployed faster-whisper ASR path. NOT enabled by
# default in config/models/model_registry.yaml (asr_sherpa_onnx,
# tts_sherpa_onnx) -- zero prior references anywhere in this repo, not
# yet benchmarked. Run with --confirm to actually install; without it,
# this only prints the plan (same "print before download" pattern as
# every other script here).

set -euo pipefail

CONFIRM="${1:-}"

echo "Package:    sherpa-onnx"
echo "License:    Apache-2.0 (k2-fsa project)"
echo "Purpose:    Candidate ASR/TTS/wake-word engine per the brief's stated preference."
echo "Status:     NOT currently used anywhere in bonbon_robot_ai -- this installs the package"
echo "            only; model weights are a separate, deliberate choice (see the model registry's"
echo "            asr_sherpa_onnx/tts_sherpa_onnx entries' download_command for the exact model"
echo "            once one is selected after benchmarking)."
echo "Command:    pip install sherpa-onnx"
echo ""

if [ "${CONFIRM}" != "--confirm" ]; then
    echo "Dry run only -- pass --confirm to actually install."
    echo "(This model is enabled_by_default: false in the registry; installing the package alone"
    echo " does not make it the active ASR/TTS engine -- that requires a registry profile change"
    echo " after a real benchmark justifies it.)"
    exit 0
fi

pip install sherpa-onnx
echo "Installed. This does NOT change which ASR/TTS engine is active -- see"
echo "config/models/model_registry.yaml's enabled_by_default flags."
