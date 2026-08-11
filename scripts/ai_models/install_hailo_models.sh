#!/bin/bash
# scripts/ai_models/install_hailo_models.sh
#
# HARDWARE_BLOCKED, not a normal install script. No .hef file exists
# anywhere in this repo, and no Hailo device has ever been detected on
# the real Pi-2 hardware (docs/PI2_HARDWARE_CHECK_REPORT.md, 2026-07-06:
# "hailortcli not installed"). This script does not download anything --
# it checks for the device and prints exactly what would be needed if
# one is ever connected, rather than inventing a Model Zoo URL this
# session cannot verify.

set -euo pipefail

echo "=== Hailo AI HAT/HAT+/HAT+2 model installation ==="
echo ""
echo "Status: HARDWARE_BLOCKED"
echo ""
echo "This script requires:"
echo "  1. A physically connected Hailo device (AI HAT / HAT+ / HAT+2)"
echo "  2. hailort + hailortcli installed (Hailo's own SDK, from hailo.ai's developer zone)"
echo "  3. Access to the Hailo Model Zoo (https://github.com/hailo-ai/hailo_model_zoo) to compile"
echo "     or download a pre-compiled .hef for the target model (YOLO object/person/pose)"
echo ""

if command -v hailortcli >/dev/null 2>&1; then
    echo "hailortcli found -- scanning for a device:"
    hailortcli scan
else
    echo "BLOCKED: hailortcli is not installed on this machine."
    echo "Nothing to download until hailort is installed AND a device is detected --"
    echo "this script deliberately does not print a Model Zoo download URL until then,"
    echo "since it cannot verify one against real hardware in this environment (rule 1)."
    exit 1
fi
