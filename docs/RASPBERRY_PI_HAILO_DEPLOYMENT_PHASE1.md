# Raspberry Pi 5 + Hailo AI HAT Deployment — Phase 1: Hardware/OS Detection

**Date:** 2026-06-30
**Constraint, stated upfront:** This audit was performed from a Windows
development machine with no physical Raspberry Pi, no Hailo hardware, and no
ROS2 install. None of the 21 hardware-detection items below could be
*measured* from here — there is no Pi to measure. What follows is (1) a
ready-to-run detection script for the **actual target hardware**, and (2) a
static code audit of what the BonBon codebase currently assumes/supports for
this hardware target, which **is** verifiable without physical access.

## 1–21: Hardware/OS detection script

`scripts/pi_hardware_check.sh` already existed (camera/mic/speaker/I2C/GPIO/
USB-serial device-presence checks) — extended in this pass rather than
duplicated with a second script. It now also covers, in order:

1. Pi model (`/proc/device-tree/model`, with an explicit check that it reads "Raspberry Pi 5")
2. RAM size (via `free -h`, reused in the storage/swap section)
3. OS (`/etc/os-release`)
4. Kernel version (`uname -a`)
5. ROS2 version (`ros2 --version`, warns if not sourced)
6. Python version (`python3 --version`)
7. Architecture (`uname -m`) — **hard-fails on 32-bit**, since `ultralytics`/`onnxruntime`/`hailort` all require 64-bit
8. Available storage (`df -h /`, warns under 2GB free)
9. Swap status (`free -h`, warns if absent — flagged because concurrent vision+speech+LLM on 4-8GB RAM is a real OOM risk without it)
10. CPU governor (`scaling_governor`)
11. Temperature sensor (`vcgencmd measure_temp`, falls back to `thermal_zone0`)
12. Throttling state (`vcgencmd get_throttled` — fails loudly on a non-zero flag, since that means under-voltage or thermal throttling has *already happened*)
13. Camera availability (existing check, `/dev/video*`)
14. Microphone availability (existing check, ALSA)
15. Speaker/audio output (existing check, ALSA playback)
16. LIDAR (existing check, `/dev/ttyUSB*`)
17. IMU (existing check, I2C @0x68)
18. Motor controller / servos (existing check, `/dev/ttyUSB*`)
19. Display (new — checks `DISPLAY`/`/dev/fb0`; explicitly notes headless-with-remote-dashboard is fine, BonBon's dashboard is browser-based)
20. AI HAT / Hailo device detection (new — `lspci | grep -i hailo`)
21. Hailo runtime availability (new — `hailortcli fw-control identify`, `hailortcli scan`)
22. PCIe status (covered by the `lspci` check above)
23. Power supply stability (new — `vcgencmd pmic_read_adc` where available; the throttling flag above is the more reliable proxy)

Run on the actual Pi: `bash scripts/pi_hardware_check.sh`. Verified in this
pass to run without bash runtime errors (no unbound-variable crashes under
`set -uo pipefail`) by executing it here — every check correctly reports
itself unavailable/warn on this non-Pi machine, exactly as it should.

## Static code audit: what the codebase currently assumes (verifiable without hardware)

**This is the most important finding of Phase 1.** `bonbon_vision`'s YOLO
detector (`bonbon_vision/detectors/yolo_detector.py`) — the actual object
detection inference path — has this in its own docstring:

> "Recommended models for the **Jetson Orin Nano**... `yolo export
> model=yolov8n.pt format=engine device=0 half=True` → produces
> `yolov8n.engine`"

The codebase was originally documented and scoped for an **NVIDIA Jetson**
target (TensorRT `.engine` export), not Raspberry Pi + Hailo. Concretely:

- `YoloDetector.load_model()` calls `ultralytics.YOLO(model_path)` directly,
  supporting `.pt` (PyTorch), `.engine` (TensorRT), and `.onnx` (via
  onnxruntime) — **there is no HailoRT (`.hef`) loading path anywhere**.
  Hailo's toolchain compiles ONNX models to `.hef`, but `.hef` files require
  the separate `hailort` Python runtime to execute, not onnxruntime or
  ultralytics' generic loader. Pointing `model_path` at a `.hef` file would
  not work with the current code.
- `grep -rl "hailo" --include=*.py` across the entire workspace: **zero
  matches**. No Hailo driver, no Hailo-aware detector, no Hailo health
  reporting, nothing.
- `deployment/docs/raspberry_pi.md` (the existing, real, substantial Pi
  deployment guide) does not mention Hailo or an AI HAT anywhere — it covers
  USB camera/mic, I2C IMU/battery, GPIO e-stop, and USB-serial LIDAR/servos
  only, with vision inference performance tuned by "the smallest YOLO model"
  running on CPU.

**Practical consequence:** as the codebase stands today, running BonBon's
vision pipeline on a Pi 5 means YOLO inference runs on the Pi's ARM CPU via
ultralytics' CPU fallback — which directly contradicts critical requirement
#7 ("AI HAT must be used for supported vision inference workloads") and
risks #8 ("CPU must be protected from continuous heavy AI load") under
sustained inference. Building a `HailoDetector(BaseDetector)` backend (the
existing `base_detector.py` interface that `YoloDetector`/`MockDetector`
already implement) is the concrete next step — not attempted in this Phase 1
pass, since the brief explicitly scoped this phase to detection/audit only.

## What's already in good shape for a Pi deployment

- `deployment/docs/raspberry_pi.md` is real, detailed, and already covers
  USB camera/mic/IMU/battery/e-stop/LIDAR/servo bring-up with a working
  `bonbon_hal/config/hal_pi.yaml` profile.
- `scripts/pi_hardware_check.sh` already existed and covers device presence
  correctly (now extended, not duplicated, with system/thermal/Hailo checks).
- The HAL's USB camera/mic drivers (`usb_camera_driver.py`,
  `usb_mic_driver.py`) and the GPIO e-stop driver
  (`gpio_estop_driver.py`) are already Pi-targeted (confirmed by direct
  inspection, not assumed).
- `bonbon_safety`'s `ResourceMonitor` (CPU/memory/disk, wired to
  `/bonbon/system/resource_usage` this session) and
  `bonbon_perception_efficiency`'s `LoadSheddingController` (now also
  thermal-aware, wired this session) already provide the load-shedding
  primitives critical requirement #8 needs — they just don't yet have a
  Hailo-specific signal (NPU utilization/temperature) feeding into them,
  since no Hailo telemetry source exists yet.

## Honest scope note

Per the brief's own phasing, this pass stopped at detection/audit and did
not implement a Hailo detector backend, Hailo-aware load shedding, or any
other Phase 2+ work — consistent with this project's established "do not
write code before the audit" discipline from earlier phases of this
engagement.
