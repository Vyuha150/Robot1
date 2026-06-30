#!/usr/bin/env bash
# Raspberry Pi hardware self-test for BonBon.
# Detects the Pi/OS/ROS2 system itself, the AI HAT/Hailo accelerator, and the
# external camera, microphone, I2C sensors, GPIO and USB-serial devices the
# HAL expects, then prints a clear PASS/WARN report. Run this BEFORE launching
# with hal_pi.yaml so device/version mismatches are caught early.
#
#   bash scripts/pi_hardware_check.sh
#
# Exit code 0 = all critical devices present; 1 = a critical device is missing.
#
# This MUST be run on the actual target hardware -- there is no way to detect
# real Raspberry Pi / Hailo hardware from a dev machine that doesn't have it.
set -uo pipefail

pass=0; warn=0; fail=0
ok()   { echo "  [PASS] $1"; pass=$((pass+1)); }
warns(){ echo "  [WARN] $1"; warn=$((warn+1)); }
bad()  { echo "  [FAIL] $1"; fail=$((fail+1)); }
have() { command -v "$1" >/dev/null 2>&1; }

echo "════════ BonBon Raspberry Pi hardware check ════════"

# ── System / OS / ROS2 / Python ────────────────────────────────────────────────
echo "System:"
if [[ -f /proc/device-tree/model ]]; then
  model=$(tr -d '\0' < /proc/device-tree/model)
  ok "model: $model"
  [[ "$model" == *"Raspberry Pi 5"* ]] || warns "not detected as a Pi 5 -- BonBon targets Pi 5 + AI HAT specifically"
else
  warns "/proc/device-tree/model not present (not running on a Pi, or device tree unavailable)"
fi
ok "kernel: $(uname -a)"
if [[ -f /etc/os-release ]]; then
  . /etc/os-release
  ok "OS: ${PRETTY_NAME:-unknown}"
else
  warns "/etc/os-release missing"
fi
arch=$(uname -m)
[[ "$arch" == "aarch64" || "$arch" == "arm64" ]] && ok "architecture: $arch (64-bit, required)" \
  || bad "architecture: $arch -- BonBon requires 64-bit (aarch64/arm64); 32-bit (armhf) is NOT supported by ultralytics/onnxruntime/hailort"
have python3 && ok "python3: $(python3 --version 2>&1)" || bad "python3 not found"
if have ros2; then
  ok "ros2: $(ros2 --version 2>&1 | head -1)"
else
  warns "ros2 CLI not on PATH (source the workspace install/setup.bash first)"
fi

# ── Storage / swap ─────────────────────────────────────────────────────────────
echo "Storage:"
df -h / 2>/dev/null | awk 'NR==2{printf "  [INFO] root: %s used / %s total (%s used)\n", $3, $2, $5}'
avail_kb=$(df --output=avail / 2>/dev/null | tail -1 | tr -d ' ')
if [[ -n "${avail_kb:-}" ]] && [[ "$avail_kb" -lt 2097152 ]]; then
  warns "less than 2GB free on root -- model files + logs + the data store need headroom"
else
  ok "sufficient free disk space"
fi
swap_total=$(free -h 2>/dev/null | awk '/^Swap:/{print $2}')
if [[ "${swap_total:-0}" == "0" || "${swap_total:-0B}" == "0B" ]]; then
  warns "no swap configured -- a Pi 5 with 4-8GB RAM running vision+speech+LLM concurrently can OOM without it"
else
  ok "swap: $swap_total"
fi

# ── CPU governor / temperature / throttling ────────────────────────────────────
echo "CPU / thermal:"
gov_path="/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
if [[ -f "$gov_path" ]]; then
  gov=$(cat "$gov_path")
  [[ "$gov" == "performance" || "$gov" == "ondemand" || "$gov" == "schedutil" ]] \
    && ok "CPU governor: $gov" \
    || warns "CPU governor: $gov (consider 'ondemand' or 'schedutil' for sustained AI workloads)"
else
  warns "scaling_governor not found at $gov_path"
fi
if have vcgencmd; then
  temp=$(vcgencmd measure_temp 2>/dev/null)
  ok "temperature: ${temp:-unavailable}"
  throttled=$(vcgencmd get_throttled 2>/dev/null)
  if [[ -n "$throttled" ]]; then
    if [[ "$throttled" == "throttled=0x0" ]]; then
      ok "throttled flag: $throttled (clean)"
    else
      bad "throttled flag: $throttled -- under-voltage or thermal throttling has occurred; check PSU and cooling"
    fi
  fi
elif [[ -f /sys/class/thermal/thermal_zone0/temp ]]; then
  t=$(($(cat /sys/class/thermal/thermal_zone0/temp) / 1000))
  ok "temperature (thermal_zone0): ${t}°C"
else
  warns "vcgencmd not found and no thermal_zone0 -- cannot read temperature (install libraspberrypi-bin)"
fi

# ── AI HAT / Hailo accelerator ──────────────────────────────────────────────────
echo "AI HAT / Hailo accelerator:"
if have lspci && lspci 2>/dev/null | grep -qi hailo; then
  ok "Hailo device on PCIe: $(lspci 2>/dev/null | grep -i hailo)"
elif have lspci; then
  warns "no Hailo device found on PCIe (lspci) -- check the HAT is seated and PCIe is enabled in /boot/firmware/config.txt"
else
  warns "lspci not found (install pciutils) -- cannot check PCIe for the Hailo device"
fi
if have hailortcli; then
  if hailortcli fw-control identify >/dev/null 2>&1; then
    ok "hailortcli fw-control identify: $(hailortcli fw-control identify 2>&1 | head -3 | tr '\n' ' ')"
  else
    bad "hailortcli installed but fw-control identify failed -- device not responding (check power/PCIe link)"
  fi
  if have hailortcli && hailortcli scan >/dev/null 2>&1; then
    ok "hailortcli scan: $(hailortcli scan 2>&1 | tr '\n' ' ')"
  fi
else
  bad "hailortcli not found -- HailoRT runtime is not installed. NOTE: as of this check, BonBon's own vision detector (bonbon_vision/detectors/yolo_detector.py) has NO Hailo-accelerated backend yet -- it loads .pt/.engine/.onnx via ultralytics directly, with no HailoRT (.hef) path. Installing the runtime alone does not give BonBon Hailo acceleration; a dedicated detector backend is required (see PHASE2_RASPBERRY_PI_DEPLOYMENT findings)."
fi

# ── Power supply indicators ─────────────────────────────────────────────────────
echo "Power supply:"
if have vcgencmd; then
  pmic=$(vcgencmd pmic_read_adc 2>/dev/null)
  if [[ -n "$pmic" ]]; then
    ok "PMIC ADC readings available (vcgencmd pmic_read_adc)"
  else
    warns "vcgencmd pmic_read_adc returned nothing"
  fi
else
  warns "vcgencmd not available -- cannot read PMIC/under-voltage indicators directly (see throttled flag above as a proxy)"
fi

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

# ── Display ──────────────────────────────────────────────────────────────────
echo "Display:"
if [[ -n "${DISPLAY:-}" ]] || [[ -e /dev/fb0 ]] || (have tvservice && tvservice -s >/dev/null 2>&1); then
  ok "a display/framebuffer appears available (DISPLAY=${DISPLAY:-unset}, /dev/fb0 present: $([[ -e /dev/fb0 ]] && echo yes || echo no))"
else
  warns "no DISPLAY env var or /dev/fb0 -- ok for headless operation (dashboard is browser-based, accessed remotely), but a local face/status display will not work"
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
