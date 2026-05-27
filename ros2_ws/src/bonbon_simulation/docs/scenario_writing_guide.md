# Scenario Writing Guide

Scenarios live in `scenarios/*.yaml`. Each scenario declares:

- `name`
- `world`
- `seed`
- `start`
- `goal`
- `duration_sec`
- `entities`
- `events`
- `criteria`

Use reproducible seeds for every scenario. Keep pass/fail criteria explicit and tied to deployment targets, such as max collisions, emergency stop reaction time, replanning latency, and docking success rate.

Example event:

```yaml
- time_sec: 2.0
  type: sensor_failure
  target: lidar
```
