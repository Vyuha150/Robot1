#!/usr/bin/env bash
# Enable MODE B — Modular Production (Raspberry Pi). The full stack is split
# into independently restartable services. bonbon-core is DISABLED; the
# single safety supervisor is bonbon-safety. No duplicate pipelines.
#
# Use for: Raspberry Pi production robot, field deployment, service-level
# restart control.
#
#   sudo bash scripts/enable_modular_pi_mode.sh
#
# Run on the host (where systemctl lives), as root.
set -uo pipefail

MONOLITH="bonbon-core"
# Order matters: safety + HAL first, then the safety-gated subsystems.
MODULAR_ORDERED=("bonbon-safety" "bonbon-hal" "bonbon-perception" "bonbon-speech" \
                 "bonbon-behavior" "bonbon-navigation" "bonbon-actuation" "bonbon-tts")
SHARED=("bonbon-dashboard" "bonbon-monitoring")

if ! command -v systemctl >/dev/null 2>&1; then
  echo "[FAIL] systemctl not found — run this on the Pi/host, not in a container." >&2
  exit 1
fi

echo "== Enabling MODE B: modular Pi production =="

echo "-- disabling the monolithic service (avoid duplicate pipelines) --"
sudo systemctl disable --now "${MONOLITH}.service" 2>/dev/null && echo "   disabled ${MONOLITH}" \
  || echo "   ${MONOLITH} already disabled / not installed"

echo "-- enabling modular subsystem services (safety + HAL first) --"
for unit in "${MODULAR_ORDERED[@]}"; do
  sudo systemctl enable --now "${unit}.service" 2>/dev/null && echo "   enabled ${unit}" \
    || echo "   [WARN] ${unit} not installed — install deployment/systemd/${unit}.service"
done
for unit in "${SHARED[@]}"; do
  sudo systemctl enable --now "${unit}.service" 2>/dev/null && echo "   enabled ${unit}" \
    || echo "   ${unit} not installed (optional)"
done

echo "-- validating boot topology --"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "${ROOT}/scripts/validate_boot_topology.py"
rc=$?
if [[ $rc -ne 0 ]]; then
  echo "[FAIL] topology validation failed after switching to modular mode." >&2
  exit $rc
fi
echo "[PASS] modular Pi mode active — exactly one safety supervisor (bonbon-safety)."
echo "Tip: confirm at runtime with: bash scripts/check_duplicate_ros_nodes.sh"
