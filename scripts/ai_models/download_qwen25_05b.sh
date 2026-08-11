#!/bin/bash
# scripts/ai_models/download_qwen25_05b.sh
#
# Pulls the ONE approved local LLM (qwen2.5:0.5b, Apache-2.0, already
# verified working on real Pi-2 hardware 2026-07-06 -- see
# docs/PI2_QWEN25_05B_SETUP_REPORT.md). Does NOT pull llama3.2:1b or
# qwen2.5:1.5b -- those are benchmark-only candidates requiring explicit
# approval (rule: "do not download llama3.2:1b or qwen2.5:1.5b without
# explicit approval"), never bundled into this script.

set -euo pipefail

MODEL="qwen2.5:0.5b"
LICENSE="Apache-2.0"
SIZE_MB=397
PURPOSE="Short conversational replies + RAG-grounded wording only -- text output never reaches an actuator directly."

echo "Model:      ${MODEL}"
echo "License:    ${LICENSE}"
echo "Size:       ~${SIZE_MB} MB"
echo "Purpose:    ${PURPOSE}"
echo "Target:     Pi-2 (AI Interaction Pi), via Ollama"
echo "Command:    ollama pull ${MODEL}"
echo ""

if ! command -v ollama >/dev/null 2>&1; then
    echo "BLOCKED: 'ollama' is not installed on this machine." >&2
    echo "This is expected on a non-Pi dev machine -- see docs/AI_MODEL_DOWNLOAD_AND_LICENSE_PLAN.md." >&2
    echo "qwen2.5:0.5b was already pulled on the real Pi-2 (wise150@192.168.1.16) on 2026-07-06;" >&2
    echo "this script is for re-running the same, already-approved download on a real board." >&2
    exit 1
fi

FREE_MB=$(df -Pm . | awk 'NR==2{print $4}')
if [ "${FREE_MB}" -lt "${SIZE_MB}" ]; then
    echo "BLOCKED: only ${FREE_MB}MB free, need ~${SIZE_MB}MB. Refusing to download (rule 2/9)." >&2
    exit 1
fi

ollama pull "${MODEL}"
echo ""
echo "Verifying with a real prompt (matches the brief's exact verification command):"
ollama run "${MODEL}" "Reply in one short sentence: I am BonBon, ready to help."
