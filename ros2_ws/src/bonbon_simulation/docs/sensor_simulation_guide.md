# Sensor Simulation Guide

Sensor contracts are configured in `models/bonbon_robot/config/sensor_sim.yaml`.

Required simulated sensors:

- RPLIDAR on `/scan`
- IMU on `/imu/data`
- RGB camera on `/camera/color/image_raw`
- depth camera on `/camera/depth/image_raw`
- microphone events on `/bonbon/speech/mic_event`
- speaker/TTS events on `/bonbon/tts/event`
- servo state on `/bonbon/servo/state`
- battery state on `/bonbon/battery/state`
- emergency stop state on `/bonbon/estop/state`

The headless tests use `SensorFaultInjector` to validate publishing state, failure detection latency, drift, and recovery behavior.
