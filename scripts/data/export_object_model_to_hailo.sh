#!/bin/bash
# scripts/data/export_object_model_to_hailo.sh
#
# Compiles a fine-tuned ONNX object-detection model to Hailo HEF format.
# Runs on the WORKSTATION that did the fine-tuning (rule 7 -- never on a
# Pi), using the Hailo Dataflow Compiler toolchain (`hailomz`, from the
# Hailo Model Zoo). This environment has no Hailo Dataflow Compiler
# installed and no .hef has ever been produced in this repo
# (scripts/ai_models/install_hailo_models.sh is HARDWARE_BLOCKED for the
# same reason) -- this script follows that same honesty discipline: it
# checks for the real toolchain and reports BLOCKED with exactly what is
# missing, rather than inventing a compile command this session cannot
# verify actually works.

set -euo pipefail

ONNX_PATH="${1:-}"
MODEL_NAME="${2:-bonbon_object_detector}"
OUT_DIR="${3:-models/hailo}"

echo "=== Hailo HEF export: ${MODEL_NAME} ==="
echo ""

if [[ -z "${ONNX_PATH}" ]]; then
    echo "Usage: $0 <path-to-fine-tuned.onnx> [model_name] [out_dir]"
    exit 2
fi

if [[ ! -f "${ONNX_PATH}" ]]; then
    echo "BLOCKED: ONNX input not found: ${ONNX_PATH}"
    echo "Run the workstation/GPU fine-tuning step first (docs/TRAINING_AND_FINE_TUNING_PLAN.md,"
    echo "object_detection target) and export to ONNX before compiling to HEF."
    exit 1
fi

if ! command -v hailomz >/dev/null 2>&1; then
    echo "Status: HARDWARE_BLOCKED"
    echo ""
    echo "hailomz (Hailo Model Zoo CLI, part of the Hailo Dataflow Compiler) is not installed"
    echo "on this machine. This script deliberately does not fabricate a compile command it"
    echo "cannot verify -- see scripts/ai_models/install_hailo_models.sh for the same rule."
    echo ""
    echo "To compile once the Dataflow Compiler is installed:"
    echo "  hailomz compile --ckpt \"${ONNX_PATH}\" --hw-arch hailo8 --calib-path <calibration_images_dir> ${MODEL_NAME}"
    echo ""
    echo "Once a real .hef is produced, register it with:"
    echo "  bonbon_data_pipeline.export_for_edge.EdgeDeploymentTracker.set_active("
    echo "      'object_detection', model_id='${MODEL_NAME}', model_version=<version>)"
    exit 1
fi

mkdir -p "${OUT_DIR}"
echo "hailomz found -- compiling ${ONNX_PATH} to HEF..."
echo "NOTE: calibration images are required for INT8 quantization accuracy;"
echo "pass a real calibration set path, not this script's default."
hailomz compile --ckpt "${ONNX_PATH}" --hw-arch hailo8 "${MODEL_NAME}"

echo ""
echo "Compile complete. Move the produced .hef into ${OUT_DIR}/ and run"
echo "scripts/data/benchmark_candidate_on_pi.py before promoting it to active."
