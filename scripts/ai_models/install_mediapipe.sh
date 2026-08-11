#!/bin/bash
# scripts/ai_models/install_mediapipe.sh
#
# MediaPipe is already the real, default gesture-recognition backend
# (bonbon_gesture, Holistic solution). This script exists mainly to
# surface the real installation risk pi2_requirements.txt already flags:
# aarch64 Linux wheel availability for mediapipe has historically lagged
# -- treat a failure here as a genuine BLOCKER for bonbon_gesture, not
# something to silently retry/ignore.

set -euo pipefail

echo "Package:    mediapipe"
echo "License:    Apache-2.0 (Google)"
echo "Purpose:    Gesture recognition (Holistic: pose + both hands + face-mesh), already the"
echo "            real default backend in bonbon_gesture."
echo "Command:    pip install mediapipe"
echo ""
echo "KNOWN RISK (documented in requirements/pi2_requirements.txt): mediapipe has historically had"
echo "incomplete/lagging aarch64 Linux wheel availability. If this install fails on the real Pi-2"
echo "with 'no matching distribution', that is a genuine, reportable blocker for gesture recognition"
echo "-- not something to silently skip or assume will resolve itself."
echo ""

pip install mediapipe
python3 -c "import mediapipe; print('mediapipe', mediapipe.__version__, 'importable')"
