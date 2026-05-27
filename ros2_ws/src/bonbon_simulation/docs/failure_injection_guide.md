# Failure Injection Guide

The suite supports failure injection for:

- lidar failure
- camera failure
- IMU drift
- microphone noise
- servo fault
- WiFi loss
- robot pushed event
- emergency stop
- map mismatch
- low battery
- dynamic obstacles

Failure events should include a timestamp and clear expected criteria. Sensor faults are tracked by `SensorFaultInjector`; emergency events are tracked by `EmergencyEventInjector`.
