#!/bin/bash
# scripts/pi2/check_pi2_hardware.sh
#
# Read-only hardware detection for Pi-2 (OAK-D Lite / ReSpeaker XVF3800 /
# ALSA speaker / AI HAT+2 Hailo). Never fabricates a PASS -- reports
# exactly what it finds, including "not connected" honestly. Run this
# any time hardware is plugged/unplugged to get a fresh, truthful status.

set -uo pipefail  # not -e: every check must run even if an earlier one "fails"

log() { echo "[check_pi2_hardware] $*"; }

log "=== USB devices ==="
lsusb

log ""
log "=== OAK-D Lite (Luxonis, vendor 03e7) ==="
if lsusb | grep -qi "03e7"; then
    log "FOUND: $(lsusb | grep -i 03e7)"
else
    log "NOT FOUND -- OAK-D Lite is not connected. bonbon_hal's camera_node"
    log "will honestly report a connect fault / degraded status, not fake data."
fi

log ""
log "=== ReSpeaker XVF3800 (USB audio) ==="
if lsusb | grep -qiE "respeaker|xvf|seeed"; then
    log "FOUND: $(lsusb | grep -iE 'respeaker|xvf|seeed')"
else
    log "NOT FOUND by vendor string -- checking ALSA capture devices instead"
    log "(ReSpeaker sometimes enumerates as a generic USB Audio device):"
fi

log ""
log "=== ALSA capture devices (arecord -l) ==="
arecord -l 2>&1 || log "arecord not available"

log ""
log "=== ALSA playback devices (aplay -l) ==="
aplay -l 2>&1 || log "aplay not available"

log ""
log "=== V4L2 devices (v4l2-ctl --list-devices) ==="
v4l2-ctl --list-devices 2>&1 || log "v4l2-ctl not available or no V4L2 devices (expected -- OAK-D is USB3/depthai, not V4L2)"

log ""
log "=== depthai import check (inside container, not host) ==="
log "SKIPPED on host -- depthai is installed in the bonbon/ai container image,"
log "not on the Debian 13 host (see docs/PI2_RASPBERRY_PI_PREFLIGHT_REPORT.md)."
log "Run: docker compose -f deployment/compose/docker-compose.pi2.yml exec vision python3 -c 'import depthai; print(depthai.__version__)'"

log ""
log "=== AI HAT / Hailo ==="
if command -v hailortcli >/dev/null 2>&1; then
    hailortcli scan 2>&1
else
    log "hailortcli not installed -- AI HAT+2 (Hailo-10H) integration is a"
    log "separate, deferred scope item (Phase 10 of the original 14-phase"
    log "brief), not part of this deployment pass. Not treated as a blocker."
fi

log ""
log "=== Temperature / throttling ==="
vcgencmd measure_temp 2>&1 || log "vcgencmd not available"
vcgencmd get_throttled 2>&1 || log "vcgencmd not available"

log ""
log "Done. This is a snapshot, not a pass/fail gate -- absence of camera/mic"
log "hardware is reported honestly above, not hidden."
