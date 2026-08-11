#!/bin/bash
# scripts/ai_models/install_piper_tts.sh
#
# Piper TTS is already the real, deployed English voice
# (en_US-lessac-medium, verified working on real Pi-2 hardware). This
# script (a) confirms/reinstalls the package for a fresh board, and
# (b) optionally fetches the Hindi voice that's currently MISSING
# (GAP-8) -- gated behind --with-hindi since that voice hasn't been
# benchmarked yet and its exact identifier is a deliberate choice, not
# a placeholder guess.

set -euo pipefail

WITH_HINDI="${1:-}"

echo "Package:    piper-tts"
echo "License:    MIT (Piper) + CC0/MIT (piper-voices model cards)"
echo "Purpose:    Local, offline text-to-speech."
echo "Command:    pip install piper-tts"
echo ""
pip install piper-tts

echo ""
echo "English voice: en_US-lessac-medium (already the registered default, ~63MB)"
mkdir -p models/piper
if [ ! -f "models/piper/en_US-lessac-medium.onnx" ]; then
    echo "Fetching en_US-lessac-medium..."
    curl -L -o models/piper/en_US-lessac-medium.onnx \
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
    curl -L -o models/piper/en_US-lessac-medium.onnx.json \
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"
else
    echo "Already present at models/piper/en_US-lessac-medium.onnx"
fi

if [ "${WITH_HINDI}" = "--with-hindi" ]; then
    echo ""
    echo "GAP-8 fix: fetching a Hindi Piper voice (hi_IN-pratham-medium, community voice)."
    echo "This has NOT been benchmarked against hospital vocabulary yet -- treat as a"
    echo "candidate, not a verified production voice, until scripts/ai_models/benchmark_all_models.py"
    echo "has run a real TTS benchmark case against it."
    curl -L -o models/piper/hi_IN-pratham-medium.onnx \
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/hi/hi_IN/pratham/medium/hi_IN-pratham-medium.onnx" || \
        echo "WARNING: Hindi voice download failed or URL changed -- verify at https://huggingface.co/rhasspy/piper-voices before retrying" >&2
else
    echo ""
    echo "Hindi/Telugu voices NOT fetched (GAP-8, still open) -- re-run with --with-hindi to fetch"
    echo "the Hindi candidate. No Telugu Piper voice is known to exist in the piper-voices project"
    echo "as of this pass -- Telugu TTS remains an open gap regardless of this flag."
fi
