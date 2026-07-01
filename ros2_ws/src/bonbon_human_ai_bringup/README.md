# bonbon_human_ai_bringup

Pi-2 (Human AI) bringup for the three-Pi deployment
(`config/distributed/pi_human_ai.yaml`). Launches every node Pi-2 owns —
in the documented boot order — and nothing that belongs to Pi-1 or Pi-3.

This package contains no node code of its own. Every node it launches
already exists as an independently tested package
(`bonbon_hal`, `bonbon_speech`, `bonbon_llm`, `bonbon_vision`,
`bonbon_multi_person_tracker`, `bonbon_object_intelligence`,
`bonbon_gesture`, `bonbon_affective_ai`, `bonbon_human_state_fusion`,
`bonbon_speaker_intelligence`, `bonbon_tts`, `bonbon_distributed_safety`,
`bonbon_authority_manager`) — this is composition, not new functionality.

## Why this package had to exist

The Phase 1 audit
([`docs/DISTRIBUTED_DEPLOYMENT_BLOCKERS.md`](../../../docs/DISTRIBUTED_DEPLOYMENT_BLOCKERS.md),
Blocker 2) found no per-Pi launch file existed anywhere — only
`bonbon_bringup`'s full monolithic stack and per-subsystem launch files
designed for single-Pi systemd modularity, not physical Pi separation.
Without this package, there was no single command that brings up
"everything Pi-2 needs and nothing else."

## What it deliberately does NOT launch

`bonbon_hal`'s lidar/servo/motor/estop/battery/imu nodes are explicitly
disabled (`launch_lidar:=false` etc.) — those are Pi-3 hardware. Only
camera/mic/speaker are started, using the Pi-2 hardware backends
(`config/pi2_hal_overrides.yaml`: OAK-D Lite, ReSpeaker XVF3800, generic
ALSA).

## Usage

```
ros2 launch bonbon_human_ai_bringup human_ai_bringup.launch.py driver_mode:=real
```

`driver_mode:=mock` (the default) runs entirely on mock drivers — safe on
a dev machine or CI with no Pi-2 hardware attached.
