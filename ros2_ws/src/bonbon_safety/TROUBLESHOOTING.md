# bonbon_safety — Troubleshooting Guide

---

## Quick Reference

| Symptom | Section |
|---------|---------|
| Robot stuck in INITIALIZING | [§1](#1-robot-stuck-in-initializing) |
| Robot immediately enters FAULT at startup | [§2](#2-immediate-fault-at-startup) |
| Robot stuck in SAFE_STOP | [§3](#3-robot-stuck-in-safe_stop) |
| Robot keeps entering CAUTION with no humans nearby | [§4](#4-false-caution-triggers) |
| Robot stops (DANGER) with nothing in front | [§5](#5-false-danger-triggers) |
| E-stop relay not cutting motor power | [§6](#6-estop-relay-not-cutting-power) |
| Safety state not published | [§7](#7-safety-state-not-published) |
| Watchdog reports nodes stale | [§8](#8-watchdog-stale-nodes) |
| Battery docking trigger too aggressive | [§9](#9-battery-thresholds) |
| CPU overheating FAULT in warm environment | [§10](#10-thermal-thresholds) |
| Incident database growing too large | [§11](#11-incident-database) |
| Reset service call fails | [§12](#12-reset-service-fails) |

---

## 1. Robot Stuck in INITIALIZING

**Symptom:** `/bonbon/safety/state` shows `state: 0` (INITIALIZING) for more than 15 seconds.

### Diagnosis

```bash
# Check which sensor topics are being published
ros2 topic list | grep bonbon
ros2 topic hz /bonbon/lidar/scan
ros2 topic hz /bonbon/imu/data_raw
ros2 topic hz /bonbon/battery/state

# Check supervisor logs for startup details
ros2 topic echo /bonbon/safety/event --once
journalctl -u bonbon-supervisor -n 50
```

### Causes and Fixes

**A) LIDAR not publishing**
```bash
# Check if LIDAR node is running
ros2 node list | grep lidar
# Restart LIDAR driver
ros2 lifecycle set /bonbon/lidar_node activate
```

**B) IMU not publishing**
```bash
ros2 topic echo /bonbon/imu/data_raw --once
# If silent, check USB connection to MPU-6050:
ls /dev/ttyUSB* /dev/ttyACM*
```

**C) Startup timeout too short for this hardware**  
Edit `safety_params.yaml`:
```yaml
safety_supervisor_node:
  ros__parameters:
    startup_timeout_sec: 30.0   # increase from default 15.0
```

**D) ROS2 DDS discovery issue**  
```bash
export ROS_DOMAIN_ID=42   # must match all nodes
# Check DDS participant list
ros2 daemon stop && ros2 daemon start
```

---

## 2. Immediate FAULT at Startup

**Symptom:** Robot enters FAULT within the first few seconds after boot.

### Diagnosis

```bash
# Check recent incidents
sqlite3 /var/lib/bonbon/safety_incidents.db \
    "SELECT timestamp, reason FROM incidents ORDER BY id DESC LIMIT 5;"

# Check safety events
ros2 topic echo /bonbon/safety/event
```

### Causes and Fixes

**A) Startup timeout expired**  
→ See §1 above — a sensor is not coming online.

**B) Critical node crash detected immediately**  
The watchdog has a 30-second startup grace period — if `startup_grace_sec` is  
not respected, stale detections can trigger FAULT during boot.
```bash
# Verify watchdog startup grace is active
ros2 param get /bonbon/watchdog_node startup_grace_sec
# Should return 30.0; if not, check parameter file
```

**C) E-stop GPIO reads as pressed at boot**  
The input pin may be floating or the pull-up resistor is not working.
```bash
# Check GPIO state from estop_node logs
ros2 topic echo /bonbon/estop/state
# Should be: data: false on startup
```
If `data: true` at boot, check physical e-stop button wiring and pull-up to BCM 17.

**D) CPU temperature sensor reporting garbage**  
```bash
# Check raw temperature topic
ros2 topic echo /bonbon/temperature/readings --once
# If cpu_temp_c > 90.0 immediately, the sensor is miscalibrated
```
Adjust `cpu_temp_fault_c` in `safety_params.yaml` or repair the thermal sensor.

---

## 3. Robot Stuck in SAFE_STOP

**Symptom:** `/bonbon/safety/state` shows `state: 7` (SAFE_STOP), robot won't move.

### Checklist

1. **Is the physical e-stop button released (popped out)?**  
   The button must be released before reset is accepted.

2. **Call the reset service with operator credentials:**
   ```bash
   ros2 service call /bonbon/safety/reset bonbon_srvs/srv/SafetyReset \
       "{operator_id: 'your_id', reason: 'Inspected area, cleared for operation'}"
   ```

3. **Verify relay de-asserted:**
   ```bash
   ros2 topic echo /bonbon/estop/state
   # Should become: data: false after reset
   ```

4. **If reset call fails:**
   ```bash
   # Check if reset service is running
   ros2 service list | grep safety/reset
   # If absent, supervisor node is not running — restart it
   ros2 lifecycle set /bonbon/safety_supervisor_node activate
   ```

5. **If GPIO relay stays asserted after reset:**  
   Check that `estop_node` is active (not just configured).
   ```bash
   ros2 lifecycle get /bonbon/estop_node
   ```

---

## 4. False CAUTION Triggers

**Symptom:** Robot enters CAUTION frequently with no humans visible.

### Diagnosis

```bash
# Check what is triggering CAUTION
ros2 topic echo /bonbon/safety/event | grep -A5 "CAUTION"

# Check person detection
ros2 topic echo /bonbon/perception/persons --once

# Check battery level
ros2 topic echo /bonbon/battery/state --once | grep percentage

# Check CPU temperature
ros2 topic echo /bonbon/temperature/readings --once | grep cpu
```

### Common Causes

**A) Person detection false positives**  
Large reflective objects, moving shadows, or mis-trained detection model.
```bash
# Temporarily increase caution threshold for testing only
ros2 param set /bonbon/safety_supervisor_node human_caution_m 1.5
# NEVER deploy with lower safety margins without hardware review
```

**B) Battery caution threshold too high**  
If battery reports unstable readings near 20%:
```bash
ros2 param set /bonbon/safety_supervisor_node battery_caution_pct 18.0
```

**C) CPU temperature fluctuations near 75°C**  
In warm environments, CPU may oscillate around the threshold.
```bash
ros2 param set /bonbon/safety_supervisor_node cpu_temp_caution_c 78.0
```
Or apply a thermal pad / improve airflow.

**D) LIDAR in WARN state**  
Dirty or obstructed lens; partial LIDAR ring failure.
```bash
ros2 topic echo /bonbon/lidar/scan --once | head -20
# Check range_min / range_max for abnormal values
```
Clean LIDAR lens with dry cloth. Check for firmware updates.

---

## 5. False DANGER Triggers

**Symptom:** Robot unexpectedly stops (DANGER) with nothing in front.

### Diagnosis

```bash
# Real-time safety state monitoring
ros2 topic echo /bonbon/safety/event --no-lost-messages

# Live sensor view
ros2 topic echo /bonbon/lidar/scan --once | grep "ranges\[:5\]"
ros2 topic echo /bonbon/bumper/state --once
```

### Common Causes

**A) LIDAR stale — cable/USB disconnect**  
```bash
ros2 topic hz /bonbon/lidar/scan
# If Hz drops below 5, there is a USB issue
dmesg | tail -20  # check for USB disconnect events
```
Check USB cable from Jetson to RPLIDAR S2. Use a powered USB hub if power is marginal.

**B) Bumper stuck true (physical switch fault)**  
```bash
ros2 topic echo /bonbon/bumper/state
# If always true with no contact, the switch is welded closed
```
Replace the bumper microswitch.

**C) IMU spike triggering cliff/fall detection**  
If the IMU reports a large acceleration spike (vibration, impact):
```bash
ros2 topic echo /bonbon/imu/data_raw --once | grep linear_acceleration
```
Check IMU mounting for loose screws. Consider lowering IMU sensitivity threshold.

**D) `lidar_stale_danger: true` is too aggressive**  
In low-LIDAR-reflectivity environments (glass corridors, outdoor):
```yaml
# safety_params.yaml
safety_supervisor_node:
  ros__parameters:
    lidar_stale_danger: false   # CAUTION instead of DANGER on LIDAR loss
```
**Warning:** Only lower this setting after risk assessment with a safety engineer.

---

## 6. E-Stop Relay Not Cutting Power

**Symptom:** E-stop button pressed but motors continue running.

### Immediate Action
1. Use the physical breaker on the 24V power rail as emergency backup.
2. Power off the robot completely.

### Diagnosis After Safe Shutdown

```bash
# Verify GPIO pin configuration
# Expected: BCM 17 = input, BCM 18 = relay output
ros2 param get /bonbon/estop_node estop_input_pin   # should be 17
ros2 param get /bonbon/estop_node relay_output_pin  # should be 18

# Check estop_node is ACTIVE (not just CONFIGURED)
ros2 lifecycle get /bonbon/estop_node

# Check relay output is being asserted when button is pressed
# (with robot in simulation mode for safe testing)
BONBON_SIMULATION=1 ros2 run bonbon_safety estop_node
ros2 topic echo /bonbon/estop/state
```

### Hardware Checks
- Multimeter: BCM pin 18 should read HIGH (3.3V) when e-stop is pressed.
- Relay coil: check continuity between relay coil IN and BCM 18 output.
- Relay contact: check NC contact is in series with 24V motor power rail.
- Jetson.GPIO package installed:
  ```bash
  python3 -c "import Jetson.GPIO; print('OK')"
  ```

---

## 7. Safety State Not Published

**Symptom:** `ros2 topic echo /bonbon/safety/state` shows nothing.

### Diagnosis

```bash
# Is supervisor node running?
ros2 node list | grep safety_supervisor

# Is it ACTIVE (not just CONFIGURED)?
ros2 lifecycle get /bonbon/safety_supervisor_node

# If CONFIGURED but not ACTIVE:
ros2 lifecycle set /bonbon/safety_supervisor_node activate
```

### QoS Mismatch
The safety state uses RELIABLE + TRANSIENT_LOCAL. Subscribers must match:
```bash
# Check topic info
ros2 topic info /bonbon/safety/state --verbose
# Should show: Reliability: RELIABLE, Durability: TRANSIENT_LOCAL
```
If a consumer node subscribes with BEST_EFFORT, it will never receive messages.

### Namespace Issues
All topics must be under `/bonbon` namespace:
```bash
ros2 launch bonbon_safety safety.launch.py  # correct — sets namespace
# NOT: ros2 run bonbon_safety safety_supervisor_node  # wrong namespace
```

---

## 8. Watchdog Stale Nodes

**Symptom:** `/bonbon/safety/critical_node_crashed` is `true` in steady state.

### Diagnosis

```bash
# Check watchdog health topic for stale count
ros2 topic echo /bonbon/safety/watchdog_node/health --once

# Check which nodes are not publishing health
for topic in $(ros2 topic list | grep health); do
    count=$(ros2 topic hz $topic --window 5 2>/dev/null | grep average | awk '{print $3}')
    echo "$topic: ${count:-SILENT} Hz"
done
```

### Common Fixes

**A) Node crashed — check with systemctl:**
```bash
systemctl status bonbon-lidar bonbon-detection bonbon-nav2
journalctl -u bonbon-lidar -n 30
```

**B) Startup grace period too short:**
```yaml
watchdog_node:
  ros__parameters:
    startup_grace_sec: 60.0   # increase for slow hardware
```

**C) Node publishes health at wrong rate:**  
If `ekf_node` is expected at 1 Hz but actually runs at 0.5 Hz, adjust the registry:
```python
# In watchdog_node.py, DEFAULT_MANAGED_NODES:
ManagedNode("ekf_node", "...", NodeClass.ESSENTIAL, expected_period_sec=2.0)
```

**D) Health topic namespace mismatch:**
```bash
# Expected: /bonbon/spatial/lidar_node/health
# Check actual topic published by the node
ros2 topic list | grep health
```

---

## 9. Battery Thresholds

**Symptom:** Robot docks too eagerly (or too late).

### Adjust thresholds

```yaml
# safety_params.yaml
safety_supervisor_node:
  ros__parameters:
    battery_caution_pct: 20.0   # start slowing down (default)
    battery_dock_pct: 10.0      # force docking (default)
```

**Important:** Setting `battery_dock_pct` below 8% risks the battery hitting cutoff  
voltage during navigation, causing a sudden power loss. Do not go below 8%.

### Battery reporting incorrect percentage

```bash
ros2 topic echo /bonbon/battery/state --once
# Check: is percentage consistent with voltage reading?
# 11.1V LiPo: 12.6V = 100%, 11.1V ≈ 50%, 9.9V ≈ 0%
```
Recalibrate the battery state estimator node if readings are inaccurate.

---

## 10. Thermal Thresholds

**Symptom:** Robot enters FAULT due to CPU temperature in a warm environment.

```yaml
# safety_params.yaml — ONLY adjust after thermal engineering review
safety_supervisor_node:
  ros__parameters:
    cpu_temp_caution_c: 75.0    # default: throttle AI inference
    cpu_temp_fault_c:   90.0    # default: FAULT (hardware damage risk)
```

**Jetson Orin Nano thermal design limit: 95°C (Tjmax)**  
Do not raise `cpu_temp_fault_c` above 90°C without explicit hardware approval.

### Reduce CPU temperature
```bash
# Check current temperature
cat /sys/devices/virtual/thermal/thermal_zone*/temp

# Set power mode (lower = cooler)
sudo nvpmodel -m 1     # 10W mode
sudo jetson_clocks --restore

# Check fan speed
sudo jetson_clocks --show | grep Fan
```

---

## 11. Incident Database

**Symptom:** SQLite file growing too large.

```bash
# Check size
ls -lh /var/lib/bonbon/safety_incidents.db

# Count incidents
sqlite3 /var/lib/bonbon/safety_incidents.db "SELECT COUNT(*) FROM incidents;"

# Archive incidents older than 30 days
sqlite3 /var/lib/bonbon/safety_incidents.db \
    "DELETE FROM incidents WHERE timestamp < datetime('now', '-30 days');"
sqlite3 /var/lib/bonbon/safety_incidents.db "VACUUM;"
```

Set up a cron job for automatic archival:
```bash
# /etc/cron.weekly/bonbon-incident-archive
#!/bin/bash
sqlite3 /var/lib/bonbon/safety_incidents.db \
    "DELETE FROM incidents WHERE timestamp < datetime('now', '-90 days'); VACUUM;"
```

---

## 12. Reset Service Fails

**Symptom:** `ros2 service call /bonbon/safety/reset` returns `success: false`.

### Common Causes

**A) Robot not in FAULT or SAFE_STOP**  
The reset service only accepts calls when the robot is in a latchable state.
```bash
ros2 topic echo /bonbon/safety/state --once | grep state
# Only call reset if state is 6 (FAULT) or 7 (SAFE_STOP)
```

**B) E-stop button still physically pressed**  
Check that the button is released (popped out) before calling reset for SAFE_STOP.

**C) Service not available**
```bash
ros2 service list | grep safety/reset
# If absent: supervisor not running or not ACTIVE
ros2 lifecycle set /bonbon/safety_supervisor_node activate
```

**D) Wrong service type**
```bash
ros2 service type /bonbon/safety/reset
# Must be: bonbon_srvs/srv/SafetyReset
# If different, there is a stale service from an old node version
ros2 daemon stop && ros2 daemon start
```

---

## Log File Locations

| Log | Location |
|-----|---------|
| ROS2 node logs | `~/.ros/log/latest/` |
| Incident database | `/var/lib/bonbon/safety_incidents.db` |
| systemd service logs | `journalctl -u bonbon-safety` |
| Kernel/GPIO errors | `dmesg | grep gpio` |

---

## Escalation Contact

If an issue cannot be resolved using this guide:

1. Collect logs: `ros2 bag record /bonbon/safety/state /bonbon/safety/event /bonbon/estop/state -d 60`
2. Export incident DB: `sqlite3 /var/lib/bonbon/safety_incidents.db .dump > incidents_export.sql`
3. File issue with hardware revision, software version, and full log bundle.
