# bonbon_patient_kiosk_bringup

Bringup for the dedicated patient-facing kiosk screen. Launches
`bonbon_patient_kiosk` and nothing else — no node code of its own,
composition only, mirroring `bonbon_ui_api_bringup`'s pattern for Pi-1's
staff dashboard.

## Why a separate bringup

Per the plan decision recorded when `bonbon_patient_kiosk` was created,
the patient kiosk runs on its **own screen/host**, not on Pi-1 alongside
`bonbon_operator_api` (the staff dashboard). Keeping bringup separate too
means the patient screen can be deployed, restarted, or scaled
independently of staff tooling, and a patient never has any path to
operator-only endpoints even at the process level.

## Usage

```
ros2 launch bonbon_patient_kiosk_bringup patient_kiosk_bringup.launch.py
ros2 launch bonbon_patient_kiosk_bringup patient_kiosk_bringup.launch.py port:=8090
```

## Touchscreen kiosk mode

See `devops/scripts/launch_patient_kiosk.sh` at the repo root — a
systemd-invoked shell script (not a ROS2 launch action) that waits for
this bringup's health endpoint before opening a kiosk-mode browser
pointed at the frontend, mirroring `devops/scripts/launch_kiosk.sh` for
Pi-1's staff dashboard.
