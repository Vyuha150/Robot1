# bonbon_ui_api_bringup

Pi-1 (System UI/API) bringup for the three-Pi deployment. Launches
every node Pi-1 owns and nothing that belongs to Pi-2 or Pi-3.

This package contains no node code of its own. Every node it launches
already exists as an independently tested package
(`bonbon_operator_api`, `bonbon_fault_manager`,
`bonbon_distributed_safety`, `bonbon_authority_manager`) — this is
composition, not new functionality, mirroring
`bonbon_human_ai_bringup`'s Pi-2 pattern.

## What it launches

1. `bonbon_operator_api` — dashboard/operator API serving the 10.1"
   touchscreen.
2. `bonbon_fault_manager` — the component fault registry. It runs on
   Pi-1, not Pi-2/Pi-3, because its sole consumer (the dashboard above)
   is co-located here, and it subscribes to `/bonbon/hal/fault` /
   `/bonbon/safety/state` network-wide via normal DDS discovery (all
   three Pis share `ROS_DOMAIN_ID`) — no bridging needed, and running
   three redundant instances would be pointless duplication.
3. Cross-Pi liveness + authority (`self_id=pi1`).

## What it deliberately does NOT launch

No `bonbon_hal` include at all — per the confirmed BOM, Pi-1 is a plain
Raspberry Pi 5 with no AI HAT and no sensors/actuators, just the 10.1"
HDMI capacitive touchscreen. There is nothing for Pi-1's HAL layer to
own.

## Touchscreen kiosk mode

The 10.1" touchscreen runs a browser pointed at the dashboard UI in
kiosk mode — see `scripts/launch_kiosk.sh` (thin wrapper) /
`devops/scripts/launch_kiosk.sh` (implementation) at the repo root.
This is a systemd-invoked shell script, not a ROS2 launch action, and
runs independently of this package.

## Usage

```
ros2 launch bonbon_ui_api_bringup ui_api_bringup.launch.py
ros2 launch bonbon_ui_api_bringup ui_api_bringup.launch.py port:=8080
```
