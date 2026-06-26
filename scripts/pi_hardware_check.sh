#!/usr/bin/env bash
# Raspberry Pi hardware self-test for BonBon.
# Detects the external camera, microphone, I2C sensors, GPIO and USB-serial
# devices the HAL expects, and prints a clear PASS/WARN report. Run this BEFORE
# launching with hal_pi.yaml so device mismatches are caught early.
#
#   bash scripts/pi_hardware_check.sh
#
# Exit code 0 = all critical devices present; 1 = a critical device is missing.
set -uo pipefail

pass=0; warn=0; fail=0
ok()   { echo "  [PASS] $1"; pass=$((pass+1)); }
warns(){ echo "  [WARN] $1"; warn=$((warn+1)); }
bad()  { echo "  [FAIL] $1"; fail=$((fail+1)); }
have() { command -v "$1" >/dev/null 2>&1; }

echo "════════ BonBon Raspberry Pi hardware check ════════"

# ── Camera (USB / V4L2) ───────────────────────────────────────────────────────
echo "Camera (USB/V4L2):"
if ls /dev/video* >/dev/null 2>&1; then
  for d in /dev/video*; do
    if have v4l2-ctl; then
      name=$(v4l2-ctl -d "$d" --info 2>/dev/null | awk -F': ' '/Card type/{print $2; exit}')
      ok "$d ${name:+($name)}"
    else
      ok "$d (install v4l-utils for details: sudo apt install v4l-utils)"
    fi
  done
else
  bad "no /dev/video* — plug in a USB webcam (CRITICAL for vision)"
fi

# ── Microphone (ALSA) ─────────────────────────────────────────────────────────
echo "Microphone (USB/ALSA):"
if have arecord; then
  if arecord -l 2>/dev/null | grep -q '^card'; then
    arecord -l 2>/dev/null | awk '/^card/{print "  [PASS] "$0}'
  else
    bad "no ALSA capture device — plug in a USB mic (CRITICAL for speech)"
  fi
else
  warns "arecord not found (install alsa-utils: sudo apt install alsa-utils)"
fi

# ── Speaker (ALSA playback) ───────────────────────────────────────────────────
echo "Speaker (ALSA):"
if have aplay && aplay -l 2>/dev/null | grep -q '^card'; then
  ok "ALSA playback device present"
else
  warns "no ALSA playback device (TTS audio will be silent)"
fi

# ── I2C sensors (IMU 0x68, battery 0x40) ──────────────────────────────────────
echo "I2C bus (IMU / battery monitor):"
if [[ -e /dev/i2c-1 ]]; then
  ok "/dev/i2c-1 present"
  if have i2cdetect; then
    addrs=$(i2cdetect -y 1 2>/dev/null | grep -oE '\b(68|40)\b' | tr '\n' ' ')
    [[ "$addrs" == *68* ]] && ok "IMU @0x68 detected"      || warns "IMU @0x68 not detected"
    [[ "$addrs" == *40* ]] && ok "battery @0x40 detected"  || warns "battery monitor @0x40 not detected"
  else
    warns "i2cdetect not found (install i2c-tools: sudo apt install i2c-tools)"
  fi
else
  warns "/dev/i2c-1 missing — enable I2C: sudo raspi-config → Interface → I2C"
fi

# ── GPIO (e-stop) ─────────────────────────────────────────────────────────────
echo "GPIO (e-stop):"
if [[ -e /dev/gpiomem || -e /dev/gpiochip0 ]]; then
  ok "GPIO available (e-stop on BCM17, relay on BCM18)"
else
  bad "no GPIO device — e-stop cannot run (CRITICAL on a physical robot)"
fi

# ── USB serial (LIDAR /dev/ttyUSB0, servos /dev/ttyUSB1) ───────────────────────
echo "USB serial (LIDAR / servos):"
if ls /dev/ttyUSB* >/dev/null 2>&1; then
  for d in /dev/ttyUSB*; do ok "$d"; done
else
  warns "no /dev/ttyUSB* (LIDAR + servos use USB serial; ok if not yet connected)"
fi

# ── Python deps for the USB drivers ───────────────────────────────────────────
echo "Python driver deps:"
python3 -c "import cv2"          2>/dev/null && ok "opencv (cv2) installed"        || bad "opencv missing — pip install opencv-python-headless (CRITICAL for USB camera)"
python3 -c "import sounddevice"  2>/dev/null && ok "sounddevice installed"         || bad "sounddevice missing — pip install sounddevice (CRITICAL for USB mic)"

echo "════════════════════════════════════════════════════"
echo "Summary: $pass pass, $warn warn, $fail fail"
if [[ $fail -gt 0 ]]; then
  echo "RESULT: NOT READY — resolve the [FAIL] items above before deploying."
  exit 1
fi
echo "RESULT: hardware ready for BonBon (review any [WARN] items)."
