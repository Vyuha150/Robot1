# Pi-2 Hardware Check Report

Generated: 2026-07-06, via `scripts/pi2/check_pi2_hardware.sh` run on `wise150@192.168.1.16`.

## Result: no Pi-2 sensor/actuator peripherals currently connected

| Component | Status | Detail |
|---|---|---|
| OAK-D Lite (Luxonis, vendor `03e7`) | **NOT FOUND** | Only USB root hubs enumerate on all 4 buses |
| ReSpeaker XVF3800 | **NOT FOUND** | No matching vendor string; no ALSA capture devices at all |
| ALSA capture devices | **NONE** | `arecord -l` returns an empty device list |
| ALSA playback devices | HDMI only | `card 0/1: vc4hdmi0/1` (the Pi's own HDMI audio out) — no PAM8610/external speaker seen |
| V4L2 devices | Pi camera ISP only | `pispbe`/`rpi-hevc-dec` — these are the Pi 5's own camera-processing pipeline devices, unrelated to OAK-D (which is USB3/depthai, never appears under V4L2) |
| AI HAT / Hailo (`hailortcli`) | Not installed | Deferred scope (Phase 10 of the original 14-phase brief), not part of this pass |
| Temperature | 45.0°C | Healthy |
| Throttling | `0x0` | None |

## Implication

This is a clean board with no Pi-2 sensors physically attached yet. Everything downstream of
this (Docker build, container launch, ROS2 node activation) will come up honestly in
"hardware unavailable" degraded mode for camera/mic/speaker — `bonbon_hal`'s `DriverBase`
reports `DriverFault`/`DEGRADED` status rather than fabricating sensor data, exactly as designed.
This is expected and correct, not a deployment defect. Re-run this script any time hardware is
physically connected to get a fresh, honest status — nothing here needs to change in software
for that to work.
