# Pi-2 Code Transfer Report

Generated: 2026-07-06. Target: `wise150@192.168.1.16:/home/wise150/bonbon_robot`

## Method

Used `git archive` (not raw `rsync`/`scp -r` of the working tree) to build the bundle, scoped to
the exact package list `deployment/docker/Dockerfile.ai` already builds
(`docs/PI2_DEPLOYMENT_FILE_AUDIT.md` has the full package-by-package reasoning). This guarantees
the bundle contains only committed, clean source — no `__pycache__`, `.pytest_cache`, local venvs,
or uncommitted scratch files can leak in, since `git archive` reads from the commit object database,
not the working directory. `rsync` isn't available in this Windows environment; `scp` was used for
the single-file transfer instead (see `deploy/pi2_exclude.txt` for the pattern list, kept for
reference/future rsync use even though this transfer method didn't need it).

## What was transferred

- `deploy/pi2_manifest.txt` — 694 files (generated via `git ls-files` scoped to the Pi-2 package set)
- `deploy/pi2_deployment_bundle.tar.gz` — 667 KB, 898 tar entries (files + directories)
- Contents: 19 ROS2 packages (`bonbon_hal`, `bonbon_speech`, `bonbon_llm`, `bonbon_vision`,
  `bonbon_multi_person_tracker`, `bonbon_object_intelligence`, `bonbon_gesture`,
  `bonbon_affective_ai`, `bonbon_human_state_fusion`, `bonbon_speaker_intelligence`, `bonbon_tts`,
  `bonbon_perception_ai`, `bonbon_perception_efficiency`, `bonbon_behavior_engine`,
  `bonbon_human_ai_bringup`, `bonbon_distributed_safety`, `bonbon_authority_manager`, `bonbon_msgs`,
  `bonbon_srvs`), all of `config/`, the Pi-2 Dockerfile + compose file + systemd units, and 5
  operational scripts.

## Transfer commands used

```
ssh wise150@192.168.1.16 "mkdir -p ~/bonbon_robot"
scp deploy/pi2_deployment_bundle.tar.gz wise150@192.168.1.16:~/bonbon_robot/
ssh wise150@192.168.1.16 "cd ~/bonbon_robot && tar xzf pi2_deployment_bundle.tar.gz && rm pi2_deployment_bundle.tar.gz"
```

## Verification

```
$ ssh wise150@192.168.1.16 "find ~/bonbon_robot -type f | wc -l"
694
```

Matches the manifest's line count exactly — no files dropped or duplicated in transit. Top-level
layout on the Pi confirmed: `config/`, `deployment/`, `ros2_ws/`, `scripts/`, `.env.example`.

## Status: PASS
