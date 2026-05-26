# bonbon_hal — Hardware Abstraction Layer

Production-grade HAL for the BonBon service robot.  
**No AI module or ROS2 node may access raw hardware directly — all hardware access goes through this package.**

---

## Architecture

```
                    ┌─────────────────────────────────────┐
  AI Modules        │           ROS2 Topics               │
  (LLM, ASR, TTS)  │  /bonbon/speech/audio               │
       │            │  /bonbon/lidar/scan                 │
       │            │  /bonbon/imu/data_raw               │
       ▼            │  /bonbon/battery/state  ...         │
  ┌──────────┐      └──────────────────────────────────────┘
  │  HAL     │                     ▲
  │  ROS2    │─── reads from ──────┘
  │  Nodes   │
  └────┬─────┘
       │  uses
       ▼
  ┌──────────────────────────────────────────────┐
  │         Driver Layer (pure Python)           │
  │  CameraDriver │ LidarDriver │ ImuDriver      │
  │  ServoDriver  │ BatteryDriver │ MicDriver    │
  │  SpeakerDriver │ EstopDriver                 │
  └───────┬─────────────────────────────────────┘
          │  implements
      ┌───┴───────────┐
      │ Real drivers  │   Orbbec, RPLIDAR, MPU-6050,
      │ Mock drivers  │   Dynamixel, INA226, ReSpeaker,
      └───────────────┘   ALSA, Jetson.GPIO
```

### Key rules

1. **No raw hardware access** outside `bonbon_hal.drivers.*`
2. **Driver mode** is a ROS2 parameter: `driver_mode: real|mock`  
   Mock drivers generate realistic synthetic data — CI runs in mock mode.
3. **Fault reporting** — every driver error is published on `/bonbon/hal/fault` (`HalFault`)  
   so the Safety Supervisor can react.
4. **Reconnection** — configurable exponential-backoff (`ReconnectPolicy`) per node.
5. **Health** — every node publishes `ModuleHealth` at 1 Hz to its registered topic.

---

## Devices and Topics

| Device | Node | Data Topic | Health Topic |
|--------|------|------------|--------------|
| Orbbec Astra Mini | `camera_node` | `/bonbon/vision/camera/color/image_raw` `/bonbon/vision/camera/depth/image_raw` | `/bonbon/vision/camera_node/health` |
| RPLIDAR S2 | `lidar_node` | `/bonbon/lidar/scan` | `/bonbon/spatial/lidar_node/health` |
| MPU-6050 | `imu_node` | `/bonbon/imu/data_raw` `/bonbon/temperature/readings` | `/bonbon/spatial/imu_node/health` |
| Dynamixel | `servo_node` | `/bonbon/servo/neck/state` `/bonbon/servo/arm/state` | `/bonbon/actuation/servo_node/health` |
| INA226 | `battery_node` | `/bonbon/battery/state` | `/bonbon/power/battery_node/health` |
| ReSpeaker v2.0 | `mic_node` | `/bonbon/speech/audio` | `/bonbon/speech/mic_node/health` |
| ALSA speaker | `speaker_node` | subscribes `/bonbon/speech/audio_output` | `/bonbon/speech/speaker_node/health` |
| GPIO e-stop | `estop_hal_node` | `/bonbon/estop/state` | `/bonbon/safety/estop_node/health` |

---

## Package Structure

```
bonbon_hal/
├── bonbon_hal/
│   ├── base/
│   │   ├── driver_base.py          # Abstract DriverBase + DriverHealth
│   │   ├── reconnect_policy.py     # Exponential backoff reconnection
│   │   └── health_reporter.py      # Health/fault publishing mixin
│   ├── drivers/
│   │   ├── camera/   camera_driver.py | orbbec_driver.py  | mock_camera_driver.py
│   │   ├── lidar/    lidar_driver.py  | rplidar_driver.py | mock_lidar_driver.py
│   │   ├── imu/      imu_driver.py   | mpu6050_driver.py | mock_imu_driver.py
│   │   ├── servo/    servo_driver.py | dynamixel_driver.py | mock_servo_driver.py
│   │   ├── battery/  battery_driver.py | ina226_driver.py | mock_battery_driver.py
│   │   ├── microphone/ mic_driver.py | respeaker_driver.py | mock_mic_driver.py
│   │   ├── speaker/  speaker_driver.py | alsa_speaker_driver.py | mock_speaker_driver.py
│   │   └── estop/    estop_driver.py | gpio_estop_driver.py | mock_estop_driver.py
│   ├── nodes/
│   │   ├── hal_node_base.py        # Common LifecycleNode base (reconnect + health)
│   │   ├── camera_node.py
│   │   ├── lidar_node.py
│   │   ├── imu_node.py
│   │   ├── servo_node.py
│   │   ├── battery_node.py
│   │   ├── microphone_node.py
│   │   ├── speaker_node.py
│   │   └── estop_hal_node.py
│   └── config/
│       └── hal_params.yaml
├── launch/
│   └── hal.launch.py
├── tests/
│   ├── test_driver_base.py
│   ├── test_reconnect_policy.py
│   ├── test_lidar_driver.py
│   ├── test_imu_driver.py
│   ├── test_camera_driver.py
│   ├── test_servo_driver.py
│   ├── test_battery_driver.py
│   ├── test_estop_driver.py
│   ├── test_microphone_speaker.py
│   └── integration/
│       └── test_hal_integration.py
├── package.xml
├── setup.py
└── README.md  (this file)
```

---

## Build & Install

```bash
cd ~/ros2_ws
colcon build --packages-select bonbon_hal bonbon_msgs --symlink-install
source install/setup.bash
```

---

## Launch

```bash
# Simulation (all mock drivers, no hardware needed)
ros2 launch bonbon_hal hal.launch.py

# Full hardware
ros2 launch bonbon_hal hal.launch.py driver_mode:=real

# Partial: LIDAR + IMU only
ros2 launch bonbon_hal hal.launch.py driver_mode:=real \
    launch_camera:=false launch_mic:=false launch_speaker:=false \
    launch_servo:=false  launch_battery:=false

# With safety subsystem (launch both together)
ros2 launch bonbon_safety safety.launch.py simulation:=true &
ros2 launch bonbon_hal hal.launch.py
```

---

## Run Tests

```bash
# Fast unit tests (no ROS2, no hardware)
cd ros2_ws/src/bonbon_hal
pytest tests/ -v --ignore=tests/integration

# Integration tests (requires ROS2 environment)
colcon test --packages-select bonbon_hal
colcon test-result --verbose
```

---

## Fault Injection (tests and debugging)

All mock drivers support runtime fault injection:

```python
from bonbon_hal.drivers.lidar import MockLidarDriver

drv = MockLidarDriver()
drv.connect()

# Simulate USB disconnect after 10 reads
drv.inject_fault(disc_after=10)

# Simulate partial LIDAR ring failure (front sector blind)
drv.inject_fault(partial_ring_from_deg=330, partial_ring_to_deg=30)
```

```python
from bonbon_hal.drivers.battery import MockBatteryDriver

drv = MockBatteryDriver(initial_percent=80.0)
drv.connect()

# Simulate sudden voltage drop
drv.inject_fault(voltage_spike_v=-2.0)

# Simulate sudden SoC drop (e.g. faulty cell)
drv.inject_fault(sudden_drop_pct=30.0)
```

---

## Adding a New Hardware Driver

1. Create `bonbon_hal/drivers/<device>/<device>_driver.py` — abstract class  
2. Create `bonbon_hal/drivers/<device>/mock_<device>_driver.py` — simulation  
3. Create `bonbon_hal/drivers/<device>/real_<device>_driver.py` — hardware  
4. Create `bonbon_hal/nodes/<device>_node.py` — inherits `HalNodeBase`  
5. Add node to `launch/hal.launch.py` and `config/hal_params.yaml`  
6. Add tests in `tests/test_<device>_driver.py`  
7. Add to watchdog `DEFAULT_MANAGED_NODES` if health monitoring required  

---

## SDK Dependencies (real hardware only)

```bash
# LIDAR
pip install rplidar-robotics

# IMU + battery (I2C)
pip install smbus2

# Servos
pip install dynamixel-sdk

# Camera
pip install openni        # or: pip install pyorbbecsdk

# Microphone
pip install pyusb sounddevice numpy

# Speaker
pip install sounddevice numpy pydub

# GPIO (Jetson Orin Nano)
# Pre-installed as Jetson.GPIO; or:
pip install RPi.GPIO      # Raspberry Pi only
```

---

## Monitoring

```bash
# Watch all HAL faults
ros2 topic echo /bonbon/hal/fault

# Monitor individual device health
ros2 topic echo /bonbon/spatial/lidar_node/health
ros2 topic echo /bonbon/vision/camera_node/health

# Check LIDAR data rate
ros2 topic hz /bonbon/lidar/scan

# Check IMU data rate
ros2 topic hz /bonbon/imu/data_raw

# List all HAL topics
ros2 topic list | grep bonbon
```
