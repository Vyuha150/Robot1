#!/bin/bash
# scripts/ai_models/install_whisper_cpp.sh
#
# Builds whisper.cpp (MIT license) as a benchmark-fallback ASR engine,
# per the brief. Not enabled by default (asr_whisper_cpp in the model
# registry) -- faster-whisper is the real, already-deployed choice.
# Requires a C++ build (git clone + make), unlike the pip-installable
# alternatives -- this script reflects that honestly rather than hiding
# the build step.

set -euo pipefail

CONFIRM="${1:-}"
MODEL_SIZE="${2:-tiny}"

echo "Project:    whisper.cpp"
echo "License:    MIT (whisper.cpp) + MIT (OpenAI Whisper weights)"
echo "Purpose:    Benchmark-fallback ASR engine, compared against faster-whisper."
echo "Model size: ${MODEL_SIZE} (tiny~75MB, base~142MB)"
echo "Build:      git clone + make (C++ build, not pip-installable)"
echo ""

if [ "${CONFIRM}" != "--confirm" ]; then
    echo "Dry run only -- pass --confirm [tiny|base] to actually clone and build."
    exit 0
fi

if [ ! -d "whisper.cpp" ]; then
    git clone https://github.com/ggerganov/whisper.cpp
fi
cd whisper.cpp
bash ./models/download-ggml-model.sh "${MODEL_SIZE}"
make -j"$(nproc 2>/dev/null || echo 2)"
echo "Built. Binary at whisper.cpp/main, model at whisper.cpp/models/ggml-${MODEL_SIZE}.bin"
