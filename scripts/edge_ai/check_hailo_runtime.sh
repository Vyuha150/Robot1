#!/usr/bin/env bash
# Edge AI Runtime brief, Phase 11. Genuinely new script (no prior
# standalone Hailo-only check existed -- scripts/ai_models/precheck_models.py
# checks Hailo as one of many things; scripts/ai_models/install_hailo_models.sh
# downloads/compiles models, neither is a focused runtime-only check).
#
# Delegates the actual detection to the REAL, already-tested
# bonbon_ai_runtime.hailo_device_detector.HailoDeviceDetector (device
# PCIe presence via hailortcli/lspci + hailort Python bindings) rather
# than reimplementing that logic a third time in shell -- see
# docs/DUPLICATE_PIPELINE_AUDIT.md.
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

PYTHON_BIN="${PYTHON_BIN:-python3}"
DETECTOR_DIR="$ROOT_DIR/ros2_ws/src/bonbon_ai_runtime"
if [ -x "$ROOT_DIR/.venv/Scripts/python.exe" ]; then
    PYTHON_BIN="$ROOT_DIR/.venv/Scripts/python.exe"
    # Native Windows python.exe under Git Bash needs a Windows-style path,
    # not the POSIX-style /c/... path $ROOT_DIR resolves to -- cygpath is
    # the standard MSYS/Git-Bash utility for this exact translation. On
    # the real Pi (Linux, this script's actual target) cygpath doesn't
    # exist and DETECTOR_DIR is already correct as-is.
    if command -v cygpath > /dev/null 2>&1; then
        DETECTOR_DIR="$(cygpath -w "$DETECTOR_DIR")"
    fi
elif [ -x "$ROOT_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
fi

exec "$PYTHON_BIN" -c "
import sys
sys.path.insert(0, r'''$DETECTOR_DIR''')
from bonbon_ai_runtime.hailo_device_detector import HailoDeviceDetector

result = HailoDeviceDetector().detect()
print(f'Hailo device present (PCIe/hailortcli scan): {result.device_present}')
print(f'hailort Python runtime importable:           {result.runtime_available}')
print(f'Usable (both required):                       {result.usable}')
sys.exit(0 if result.usable else 1)
"
