#!/usr/bin/env bash
# Enable MODE A — Monolithic Bringup. bonbon-core runs the complete stack
# (including the single safety supervisor) via bringup.launch.py. Every
# per-subsystem service is DISABLED so there is no duplicate pipeline.
#
# Use for: simulation, local development, simple lab bring-up.
#
#   sudo bash scripts/enable_monolithic_mode.sh
#
# Run on the host (where systemctl lives), as root.
set -uo pipefail

MONOLITH="bonbon-core"
SHARED=("bonbon-dashboard" "bonbon-monitoring")
MODULAR=("bonbon-safety" "bonbon-hal" "bonbon-perception" "bonbon-speech" \
         "bonbon-behavior" "bonbon-navigation" "bonbon-actuation" "bonbon-tts")

if ! command -v systemctl >/dev/null 2>&1; then
  echo "[FAIL] systemctl not found — run this on the Pi/host, not in a container." >&2
  exit 1
fi

echo "== Enabling MODE A: monolithic bringup =="

echo "-- disabling per-subsystem services (avoid duplicate pipelines) --"
for unit in "${MODULAR[@]}"; do
  sudo systemctl disable --now "${unit}.service" 2>/dev/null && echo "   disabled ${unit}" \
    || echo "   ${unit} already disabled / not installed"
done

echo "-- enabling monolithic + shared services --"
sudo systemctl enable --now "${MONOLITH}.service" && echo "   enabled ${MONOLITH}"
for unit in "${SHARED[@]}"; do
  sudo systemctl enable --now "${unit}.service" 2>/dev/null && echo "   enabled ${unit}" \
    || echo "   ${unit} not installed (optional)"
done

echo "-- validating boot topology --"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "${ROOT}/scripts/validate_boot_topology.py"
rc=$?
if [[ $rc -ne 0 ]]; then
  echo "[FAIL] topology validation failed after switching to monolithic mode." >&2
  exit $rc
fi
echo "[PASS] monolithic mode active — exactly one safety supervisor (inside bonbon-core)."
