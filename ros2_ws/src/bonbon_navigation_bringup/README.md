# bonbon_navigation_bringup

Pi-3 (Navigation/Motion/Safety) bringup for the three-Pi deployment
(`config/distributed/pi_navigation_safety.yaml`). Launches every node
Pi-3 owns — in a safety-first boot order — and nothing that belongs to
Pi-1 or Pi-2.

This package contains no node code of its own. Every node it launches
already exists as an independently tested package (`bonbon_safety`,
`bonbon_hal`, `bonbon_base_controller`, `bonbon_actuation`,
`bonbon_motion_approval_gateway`, `bonbon_navigation`,
`bonbon_distributed_safety`, `bonbon_authority_manager`) — this is
composition, not new functionality, mirroring
`bonbon_human_ai_bringup`'s Pi-2 pattern exactly.

## Boot order

`bonbon_safety` (safety_supervisor, safety_gate, watchdog, estop) is
launched **first** — `safety_gate_node` is the sole CLASS-A gated path
every actuation command must pass through, and it must exist before any
HAL actuator node (servo/stepper/motor) starts being commanded.

1. `bonbon_safety` — safety_supervisor_node, safety_gate_node,
   watchdog_node, estop_node
2. `bonbon_hal` — lidar, motor, servo, stepper, estop, imu, battery
   (camera/mic/speaker explicitly disabled — Pi-2 hardware)
3. `bonbon_base_controller` — diff-drive kinematics over `motor_node`
4. `bonbon_actuation` — gesture execution (routes through
   `safety_gate_node`, never directly to `bonbon_hal`)
5. `bonbon_motion_approval_gateway` — proposal → approved-command chain
6. `bonbon_navigation` — Nav2 + RTAB-Map localization
7. Cross-Pi liveness + authority (`self_id=pi3`)

## What it deliberately does NOT launch

`bonbon_hal`'s camera/mic/speaker nodes are explicitly disabled
(`launch_camera:=false` etc.) — those are Pi-2 hardware. Only
lidar/motor/servo/stepper/estop/imu/battery are started, using the
Pi-3 hardware backends (`config/pi3_hal_overrides.yaml`: PCA9685 servo,
NEMA17 closed-loop stepper; Cytron MDDS30/RPLiDAR/MPU6050/INA226/GPIO
e-stop have no separate `backend` param — `driver_mode:=real` alone
selects each one's single real driver).

## Usage

```
ros2 launch bonbon_navigation_bringup navigation_bringup.launch.py driver_mode:=real
```

`driver_mode:=mock` (the default) runs entirely on mock drivers — safe
on a dev machine or CI with no Pi-3 hardware attached. Pass
`simulation:=true` to also run `bonbon_safety`'s `estop_node` against
`MockGPIO` instead of real GPIO.
