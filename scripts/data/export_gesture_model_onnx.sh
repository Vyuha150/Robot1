#!/bin/bash
# scripts/data/export_gesture_model_onnx.sh
#
# Exports a workstation-trained gesture landmark classifier (PyTorch
# checkpoint) to ONNX, then optionally to TFLite. Runs on the workstation
# that did the training (rule 7). Unlike the Hailo HEF path, ONNX export
# needs no special hardware -- this script actually performs the export
# when torch is available, rather than only printing a plan.

set -euo pipefail

CHECKPOINT_PATH="${1:-}"
MODEL_NAME="${2:-bonbon_gesture_classifier}"
OUT_DIR="${3:-models/gesture}"
LANDMARK_DIM="${4:-63}"  # 21 hand landmarks * 3 (x,y,z) -- override for pose landmark counts

echo "=== Gesture classifier ONNX export: ${MODEL_NAME} ==="

if [[ -z "${CHECKPOINT_PATH}" ]]; then
    echo "Usage: $0 <path-to-checkpoint.pt> [model_name] [out_dir] [landmark_dim]"
    exit 2
fi

if [[ ! -f "${CHECKPOINT_PATH}" ]]; then
    echo "BLOCKED: checkpoint not found: ${CHECKPOINT_PATH}"
    echo "Run the workstation/GPU training step first (docs/TRAINING_AND_FINE_TUNING_PLAN.md,"
    echo "gesture_recognition target) before exporting."
    exit 1
fi

if ! python3 -c "import torch" >/dev/null 2>&1; then
    echo "Status: TOOLCHAIN_BLOCKED"
    echo "PyTorch is not importable in this environment's python3 -- cannot run the export."
    echo "Install torch on the workstation (not the Pi -- rule 7) and re-run."
    exit 1
fi

mkdir -p "${OUT_DIR}"
ONNX_OUT="${OUT_DIR}/${MODEL_NAME}.onnx"

python3 - "$CHECKPOINT_PATH" "$ONNX_OUT" "$LANDMARK_DIM" <<'PYEOF'
import sys
import torch

checkpoint_path, onnx_out, landmark_dim = sys.argv[1], sys.argv[2], int(sys.argv[3])

model = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
if not isinstance(model, torch.nn.Module):
    raise SystemExit(
        f"BLOCKED: {checkpoint_path} did not load as a torch.nn.Module "
        "(got a state_dict or other object) -- this script expects a full model checkpoint; "
        "load your architecture and load_state_dict() first, then re-save the full module."
    )
model.eval()

dummy_input = torch.zeros(1, landmark_dim, dtype=torch.float32)
torch.onnx.export(
    model,
    dummy_input,
    onnx_out,
    input_names=["landmarks"],
    output_names=["gesture_logits"],
    dynamic_axes={"landmarks": {0: "batch"}, "gesture_logits": {0: "batch"}},
    opset_version=17,
)
print(f"Wrote {onnx_out}")
PYEOF

echo ""
echo "ONNX export complete: ${ONNX_OUT}"
echo "For TFLite, convert via onnx2tf or the tf.lite converter separately -- not chained here"
echo "since it requires a TensorFlow install this script does not assume is present."
echo ""
echo "Once validated, register with:"
echo "  bonbon_data_pipeline.export_for_edge.EdgeDeploymentTracker.set_active("
echo "      'gesture_recognition', model_id='${MODEL_NAME}', model_version=<version>)"
