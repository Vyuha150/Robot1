#!/usr/bin/env bash
# Vendor the dashboard's browser ML models into frontend/public/models/.
#
# The dashboard runs face-emotion (@vladmandic/face-api) and hand-gesture
# (@mediapipe/hands via @tensorflow-models/hand-pose-detection) inference in the
# browser. Vendoring the weights locally makes the dashboard work OFFLINE and
# removes the CDN 404 failure mode entirely.
#
# Run once after a fresh clone (or if public/models was gitignored):
#   bash scripts/fetch_dashboard_models.sh
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FE="$ROOT_DIR/ros2_ws/src/bonbon_operator_api/frontend"
FACE_DIR="$FE/public/models/face"
HANDS_DIR="$FE/public/models/hands"

mkdir -p "$FACE_DIR" "$HANDS_DIR"

echo "==> face models (@vladmandic/face-api)"
FACE_BASE="https://cdn.jsdelivr.net/npm/@vladmandic/face-api/model"
for f in tiny_face_detector_model-weights_manifest.json tiny_face_detector_model.bin \
         face_expression_model-weights_manifest.json face_expression_model.bin; do
  curl -fsSL --max-time 60 -o "$FACE_DIR/$f" "$FACE_BASE/$f"
  echo "   $f"
done

echo "==> hand models (@mediapipe/hands)"
# Prefer the copy installed in node_modules; fall back to the CDN.
MP_LOCAL="$FE/node_modules/@mediapipe/hands"
MP_CDN="https://cdn.jsdelivr.net/npm/@mediapipe/hands"
HAND_FILES=(hands.js hands.binarypb hands_solution_packed_assets.data
            hands_solution_packed_assets_loader.js hands_solution_simd_wasm_bin.js
            hands_solution_simd_wasm_bin.wasm hands_solution_simd_wasm_bin.data
            hand_landmark_lite.tflite hand_landmark_full.tflite)
for f in "${HAND_FILES[@]}"; do
  if [[ -f "$MP_LOCAL/$f" ]]; then
    cp "$MP_LOCAL/$f" "$HANDS_DIR/$f"
  else
    curl -fsSL --max-time 60 -o "$HANDS_DIR/$f" "$MP_CDN/$f"
  fi
  echo "   $f"
done

echo "Done. Models vendored under $FE/public/models/"
