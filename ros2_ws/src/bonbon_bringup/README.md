# bonbon_bringup

**Top-level system bring-up** for the BonBon service robot. This package owns
the single launch file that starts the *entire* robot stack in the correct
order. It is what the Docker entrypoint and `docker-compose` files invoke:

```bash
ros2 launch bonbon_bringup bringup.launch.py
```

> Before this package existed the Docker image referenced
> `bonbon_bringup bringup.launch.py` but the package was empty — the container
> could not start. This package closes that gap.

---

## What it does

`bringup.launch.py` composes every subsystem's own launch file in a deliberate
startup order and exposes launch arguments to select simulation/mock mode and to
enable or disable subsystem groups. Each subsystem still manages its own ROS2
lifecycle internally; this package only orchestrates *which* subsystems come up
and *in what order*.

### Startup order

| # | Subsystem | Why this order |
|---|---|---|
| 1 | `bonbon_data_stores` | persistence up before anything records |
| 2 | `bonbon_safety` | supervisor + e-stop before any actuator path |
| 3 | `bonbon_hal` | hardware (real drivers or mocks) |
| 4 | `bonbon_vision`, `bonbon_speech` | sensing |
| 5 | `bonbon_spatial`, `bonbon_affective_ai`, `bonbon_gesture`, `bonbon_perception_ai`, `bonbon_llm` | AI reasoning (group, `enable_ai`) |
| 6 | `bonbon_behavior_engine` | central decision engine |
| 7 | `bonbon_actuation` | expressive motion (safety-gated) |
| 8 | `bonbon_navigation` | autonomous motion (group, `enable_navigation`) |
| 9 | `bonbon_tts` | speech output |
| 10 | `bonbon_operator_api` | dashboard backend (group, `enable_operator_api`) |

---

## Launch arguments

| Argument | Default | Effect |
|---|---|---|
| `simulation` | `false` | use mock HAL drivers / simulated sensors (passed to `bonbon_hal` + `bonbon_safety`) |
| `enable_navigation` | `true` | bring up the navigation stack |
| `enable_ai` | `true` | bring up spatial / affective / gesture / perception_ai / llm |
| `enable_operator_api` | `true` | bring up the dashboard backend |
| `log_level` | `info` | ROS2 logger level |

---

## Examples

```bash
# Full real-robot stack
ros2 launch bonbon_bringup bringup.launch.py

# Headless simulation, no dashboard (CI smoke test)
ros2 launch bonbon_bringup bringup.launch.py simulation:=true enable_operator_api:=false

# Sensor bring-up / calibration only (safety + HAL + perception)
ros2 launch bonbon_bringup bringup.launch.py \
    enable_ai:=false enable_navigation:=false enable_operator_api:=false
```

---

## Testing

```bash
cd ros2_ws/src/bonbon_bringup
python -m pytest tests/ -q
```

- `tests/test_bringup_launch.py` statically validates that the launch file
  declares all expected arguments and **composes every subsystem** (guards
  against a subsystem being silently dropped from system bring-up), and — when
  run on a sourced ROS2 workspace — additionally constructs the
  `LaunchDescription` for real.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `package 'bonbon_X' not found` at launch | a subsystem not built into the workspace | `colcon build` the full `ros2_ws`; source `install/setup.bash`. |
| Robot tries to drive real motors in sim | `simulation:=false` (default) | pass `simulation:=true` for mock HAL. |
| Dashboard not reachable | `enable_operator_api:=false` | omit the flag (default true); check `bonbon_operator_api` port. |
| Navigation never starts | `enable_navigation:=false` | omit the flag (default true). |
| Subsystem starts but stays `unconfigured` | that subsystem's own lifecycle auto-config failed | check that subsystem's logs / its own launch file. |
| Container exits immediately | build failed or workspace not sourced in entrypoint | verify `Dockerfile.ros2` sources `install/setup.bash` before launch. |

### Adding a subsystem

1. Add an `_include("bonbon_newpkg", "newpkg.launch.py")` call in
   `bringup.launch.py` at the correct point in the order.
2. Add `bonbon_newpkg` to `_REQUIRED_SUBSYSTEMS` in
   `tests/test_bringup_launch.py` and to `package.xml` `<exec_depend>`.
