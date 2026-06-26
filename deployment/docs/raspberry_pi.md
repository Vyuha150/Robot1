# Raspberry Pi Deployment — External USB Camera & Microphone

Run BonBon on a Raspberry Pi (4/5, 64-bit OS) with **external USB hardware**:
a USB webcam, a USB microphone, an I2C IMU + battery monitor, GPIO e-stop, and
USB-serial LIDAR + servos. The HAL now ships generic **USB/V4L2 camera** and
**USB/ALSA microphone** drivers, so you are not tied to the Orbbec/ReSpeaker
parts.

> Safety gate: a robot deployment is refused unless the **safety supervisor**,
> **e-stop**, and a **rollback version** are available (enforced by
> `devops/scripts/pre_deploy_check.py`). Keep the e-stop on real GPIO.

---

## 0. Prerequisites (Pi OS 64-bit, ROS 2 Humble)

```bash
sudo apt update
sudo apt install -y v4l-utils alsa-utils i2c-tools \
    python3-opencv python3-pip libportaudio2
pip3 install sounddevice                 # USB mic (PortAudio)
# Enable I2C (IMU + battery): sudo raspi-config → Interface Options → I2C → enable
# Add your user to device groups:
sudo usermod -aG video,audio,i2c,gpio,dialout "$USER"   # re-login after this
```

## 1. Verify the hardware FIRST

```bash
bash scripts/pi_hardware_check.sh
```
This reports PASS/WARN/FAIL for the USB camera (`/dev/video*`), USB mic (ALSA),
speaker, I2C sensors (IMU @0x68, battery @0x40), GPIO e-stop, USB-serial, and
the Python deps. Resolve every **[FAIL]** before continuing.

Find your exact devices:
```bash
v4l2-ctl --list-devices          # which /dev/videoN is your webcam
arecord -l                       # which ALSA card is your USB mic
i2cdetect -y 1                   # confirm 0x68 (IMU) and 0x40 (battery)
```

## 2. Build the workspace on the Pi

```bash
cd ros2_ws
rosdep install --from-paths src --ignore-src -r -y --rosdistro humble
colcon build --symlink-install
. install/setup.bash
```

## 3. Launch the HAL with the Pi profile

`bonbon_hal/config/hal_pi.yaml` already selects the USB camera/mic backends and
real I2C/GPIO/serial sensors. Adjust `camera_node.device` / `mic_node.device`
to match step 1, then:

```bash
# HAL only (sensor bring-up / calibration)
ros2 launch bonbon_hal hal.launch.py \
    params_file:=$PWD/install/bonbon_hal/share/bonbon_hal/config/hal_pi.yaml

# Full robot (HAL + safety + AI + behaviour + dashboard), real hardware
ros2 launch bonbon_bringup bringup.launch.py simulation:=false
```

### Camera / mic parameters (override per robot)

| Node | Param | Meaning |
|---|---|---|
| `camera_node` | `backend: usb` | use the generic USB/V4L2 driver |
| | `device: "0"` | `/dev/video0` index (or a path string) |
| | `width/height/fps` | 640×480 @ 15 fps is a good Pi default |
| | `hfov_deg` | your lens horizontal FOV (for distance estimates) |
| `mic_node` | `backend: usb` | use the generic USB/ALSA driver |
| | `device: ""` | default input, or a name substring like `"USB"` |
| | `sample_rate: 16000` | required by VAD + Whisper downstream |

---

## 4. Docker on the Pi (optional)

The base image `ros:humble-ros-base-jammy` is multi-arch and builds on arm64.
Run the robot compose with **device passthrough** so the container sees the USB
camera, mic, I2C, GPIO and serial devices:

```yaml
# add to the 'core' (and hal) service in docker-compose.robot.yml on the Pi
devices:
  - "/dev/video0:/dev/video0"     # USB camera
  - "/dev/snd:/dev/snd"           # USB mic + speaker (ALSA)
  - "/dev/i2c-1:/dev/i2c-1"       # IMU + battery
  - "/dev/gpiomem:/dev/gpiomem"   # e-stop GPIO
  - "/dev/ttyUSB0:/dev/ttyUSB0"   # LIDAR
  - "/dev/ttyUSB1:/dev/ttyUSB1"   # servos
group_add: ["audio", "video", "i2c", "dialout", "gpio"]
```
The image already sets `BONBON_DATA_DIR=/var/bonbon/data` with a persistent
volume and a `HEALTHCHECK`, so data survives restarts and orchestrators detect a
crashed stack.

---

## 5. Performance tuning for the Pi (already defaulted in hal_pi.yaml)

- Camera at **15 fps** (not 30) — leaves CPU for inference.
- Vision detection rate / model size: prefer the smallest YOLO model and a low
  `detection_rate_hz` in `bonbon_vision` config; it drops stale frames and runs
  inference in a worker thread off the ROS2 callback.
- Speech: VAD-first gating means Whisper only runs on detected speech.
- Browser-side dashboard AI (face/gesture) runs in the **operator's** browser,
  not on the Pi — no Pi CPU cost. Access it from a laptop/phone on the LAN.

---

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `opencv (cv2) missing` | OpenCV not installed | `sudo apt install python3-opencv` |
| `sounddevice missing` | PortAudio binding absent | `pip3 install sounddevice` + `sudo apt install libportaudio2` |
| `could not open camera device 0` | wrong index or no permission | check `v4l2-ctl --list-devices`; `usermod -aG video`; set the right `device` |
| Camera opens but no frames | USB bandwidth / format | try `fourcc: "MJPG"` (already default) or lower resolution |
| `could not open microphone` | wrong ALSA device | `arecord -l`; set `mic_node.device` to the card name substring |
| IMU/battery not detected | I2C disabled or wiring | `sudo raspi-config` enable I2C; `i2cdetect -y 1` |
| e-stop won't start | no GPIO access | run on the Pi (not a container without `/dev/gpiomem`); `usermod -aG gpio` |
| High CPU / dropped frames | models too heavy for the Pi | lower `fps`, `detection_rate_hz`, use the smallest model |

Run `bash scripts/pi_hardware_check.sh` again any time the hardware set changes.
