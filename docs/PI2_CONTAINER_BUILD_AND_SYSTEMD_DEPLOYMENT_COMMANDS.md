# Pi-2 Container Build, Compose Bring-Up, and systemd Deployment — Exact Commands

**Why this doc exists:** this session's sandbox has no network route to the robot (`ssh -o ConnectTimeout=8 wise150@192.168.1.16` times out — confirmed, not assumed). Everything below is real and accurate to the artifacts already in this repo (`deployment/compose/docker-compose.pi2.yml`, `deployment/docker/Dockerfile.ai`, `deployment/systemd/pi2/*.service`), but it has **not been executed this pass**. Run it yourself from a machine that's actually on the robot's LAN (or run it directly on the Pi over its own terminal).

This covers task #85 (Phase 7: build + run the container stack) and task #86 (Phase 13-14: systemd install + final verification). It is **not** a first attempt — the compose file and Dockerfile already encode multiple real bugs found and fixed on this exact Pi-2 unit in an earlier session (the `/dev/gpiomem0` path, the single-element `command:` list, the subshell-per-job sourcing pattern, the missing `tts`/`behavior-engine` services). Treat this as resuming/verifying a mostly-proven deployment, not building one from scratch.

Target: `wise150@192.168.1.16` (Raspberry Pi 5, Debian 13 "trixie", aarch64). All commands below are meant to run **on the Pi itself** unless marked "from your workstation".

---

## 0. Prerequisites

- You're on the same LAN as the Pi (or have a working route to `192.168.1.16:22`).
- `deploy/pi2_deployment_bundle.tar.gz` was already transferred to `~/bonbon_robot` on the Pi per `docs/PI2_CODE_TRANSFER_REPORT.md` (694 files, verified). If you've changed any of the 19 ROS2 packages, `config/`, or the Pi-2 deployment files since then, re-run the transfer first:

```bash
# From your workstation, repo root
git archive --format=tar.gz -o deploy/pi2_deployment_bundle.tar.gz HEAD \
  ros2_ws/src/bonbon_hal ros2_ws/src/bonbon_speech ros2_ws/src/bonbon_llm \
  ros2_ws/src/bonbon_ai_runtime ros2_ws/src/bonbon_vision \
  ros2_ws/src/bonbon_multi_person_tracker ros2_ws/src/bonbon_object_intelligence \
  ros2_ws/src/bonbon_gesture ros2_ws/src/bonbon_affective_ai \
  ros2_ws/src/bonbon_human_state_fusion ros2_ws/src/bonbon_speaker_intelligence \
  ros2_ws/src/bonbon_tts ros2_ws/src/bonbon_perception_ai \
  ros2_ws/src/bonbon_perception_efficiency ros2_ws/src/bonbon_behavior_engine \
  ros2_ws/src/bonbon_human_ai_bringup ros2_ws/src/bonbon_distributed_safety \
  ros2_ws/src/bonbon_authority_manager ros2_ws/src/bonbon_msgs ros2_ws/src/bonbon_srvs \
  ros2_ws/src/bonbon_operator_api config requirements \
  deployment/docker/Dockerfile.ai deployment/docker/Dockerfile.dashboard-web \
  deployment/docker/dashboard-web.nginx.conf \
  deployment/compose/docker-compose.pi2.yml deployment/systemd/pi2 \
  scripts/pi2

scp deploy/pi2_deployment_bundle.tar.gz wise150@192.168.1.16:~/bonbon_robot/
ssh wise150@192.168.1.16 "cd ~/bonbon_robot && tar xzf pi2_deployment_bundle.tar.gz && rm pi2_deployment_bundle.tar.gz"
ssh wise150@192.168.1.16 "find ~/bonbon_robot -type f | wc -l"   # sanity check, should be non-zero
```

- Confirm Docker and Ollama are installed (Phase 5, already done per task #82):

```bash
ssh wise150@192.168.1.16 "docker --version && ollama --version && ollama list | grep qwen2.5"
```

---

## 1. Lay out the release directory (`/opt/bonbon/current`)

The systemd units (`deployment/systemd/pi2/*.service`) all set `WorkingDirectory=/opt/bonbon/current` and run `docker compose -f docker-compose.pi2.yml ...` from there — that's the same `/opt/bonbon/releases/<version>` + `/opt/bonbon/current` symlink convention documented in `deployment/docs/deployment_notes.md`. The code transferred so far lives in `~/bonbon_robot`, which is **not** that location yet. Wire it up:

```bash
ssh wise150@192.168.1.16 bash -s <<'EOF'
set -euo pipefail
VERSION="pi2-$(date +%Y%m%d-%H%M)"
sudo mkdir -p "/opt/bonbon/releases/$VERSION"
sudo cp -r ~/bonbon_robot/. "/opt/bonbon/releases/$VERSION/"
sudo ln -sfn "/opt/bonbon/releases/$VERSION" /opt/bonbon/current
sudo mkdir -p /etc/bonbon /var/log/bonbon /opt/bonbon/models
echo "Release: $VERSION"
echo "$VERSION" > /tmp/bonbon_pi2_version.txt
EOF
```

Keep the printed `$VERSION` — you need the identical string for `BONBON_IMAGE_TAG` below, so the image you build matches the release you just staged.

---

## 2. Provision `/etc/bonbon/bonbon.env`

`docker-compose.pi2.yml` requires `BONBON_IMAGE_TAG` on every service (`image: bonbon/ai:${BONBON_IMAGE_TAG:?set BONBON_IMAGE_TAG}`) — compose fails immediately without it. No `runtime.env` template exists for a "pi2" environment in `devops/config/` (those templates target the single-machine `docker-compose.robot.yml` path only) — this is a real, honest gap, not something to paper over. Write it directly:

```bash
ssh wise150@192.168.1.16 bash -s <<EOF
set -euo pipefail
VERSION=\$(cat /tmp/bonbon_pi2_version.txt)
sudo tee /etc/bonbon/bonbon.env >/dev/null <<ENV
BONBON_IMAGE_TAG=\$VERSION
ENV
sudo chmod 0640 /etc/bonbon/bonbon.env
cat /etc/bonbon/bonbon.env
EOF
```

`dashboard-api` on Pi-2 runs with `BONBON_TEST_MODE: "1"` hardcoded in the compose file (test/dev only, per the compose file's own comment — Pi-1 owns the real dashboard-api in production), so `BONBON_JWT_SECRET`/`BONBON_ADMIN_PASSWORD` are **not** required for this bring-up. Skip them unless you deliberately turn test mode off.

---

## 3. Build the `bonbon/ai` image on the Pi

No image registry is configured anywhere in this repo, so build natively on the Pi (arm64) rather than cross-compiling. Build context is `/opt/bonbon/current` (the release directory), since `Dockerfile.ai` copies `ros2_ws/src/...`, `config/`, and `requirements/pi2_requirements.txt` relative to that root. This step recompiles all 20 ROS2 packages and pre-bakes 3 ML models — expect **20-40+ minutes** on a Pi 5.

```bash
ssh wise150@192.168.1.16 bash -s <<'EOF'
set -euo pipefail
VERSION=$(cat /tmp/bonbon_pi2_version.txt)
cd /opt/bonbon/current
docker build -f deployment/docker/Dockerfile.ai -t "bonbon/ai:$VERSION" .
docker images bonbon/ai
EOF
```

If you also want the dashboard containers up (test/dev visibility only — see `docker-compose.pi2.yml`'s own comment on why `dashboard-api`/`dashboard-web` are co-located here rather than on Pi-1):

```bash
ssh wise150@192.168.1.16 bash -s <<'EOF'
set -euo pipefail
VERSION=$(cat /tmp/bonbon_pi2_version.txt)
cd /opt/bonbon/current
docker build -f deployment/docker/Dockerfile.dashboard-web -t "bonbon/dashboard-web:$VERSION" .
EOF
```

---

## 4. Phase 7 — bring the stack up manually and verify (before handing it to systemd)

Bring services up one at a time in dependency order so a crash-looping container is easy to isolate, rather than `up -d` on everything at once:

```bash
ssh wise150@192.168.1.16 bash -s <<'EOF'
set -euo pipefail
cd /opt/bonbon/current
export BONBON_IMAGE_TAG=$(cat /tmp/bonbon_pi2_version.txt)

for svc in hal asr vision perception-fusion llm behavior-engine tts distributed-liveness; do
  echo "--- bringing up $svc ---"
  docker compose -f deployment/compose/docker-compose.pi2.yml up -d "$svc"
  sleep 5
  docker compose -f deployment/compose/docker-compose.pi2.yml ps "$svc"
done
EOF
```

Then check every container actually stayed up (the known failure signature from earlier hardware testing was a ~100ms crash-loop with no log output — a container that's `Up` for more than the 5s sleep above already ruled that class of bug out, but confirm explicitly):

```bash
ssh wise150@192.168.1.16 "cd /opt/bonbon/current && docker compose -f deployment/compose/docker-compose.pi2.yml ps"
```

All 8 services should show `Up` (or `Up (healthy)` if healthchecks are defined) with a non-trivial uptime, not `Restarting`. If anything is restarting, get its logs before going further:

```bash
ssh wise150@192.168.1.16 "cd /opt/bonbon/current && docker compose -f deployment/compose/docker-compose.pi2.yml logs --tail=100 <service-name>"
```

Confirm the ROS2 graph came up inside the containers (run from any one container that has the workspace sourced — `hal` is a good pick since it's `network_mode: host`):

```bash
ssh wise150@192.168.1.16 "docker exec \$(docker compose -f /opt/bonbon/current/deployment/compose/docker-compose.pi2.yml ps -q hal) bash -lc 'source /opt/ros/humble/setup.bash && source /opt/bonbon/install/setup.bash && ros2 node list && ros2 topic list'"
```

If you built and want the dashboard too:

```bash
ssh wise150@192.168.1.16 "cd /opt/bonbon/current && docker compose -f deployment/compose/docker-compose.pi2.yml up -d dashboard-api dashboard-web"
```

Then from any machine on the LAN:

```bash
curl -s http://192.168.1.16:8080/api/v1/status
```

(Open the dashboard UI at `http://192.168.1.16:3000` and, per `Dockerfile.dashboard-web`'s header comment, set the "API Base URL" field to `http://192.168.1.16:8080` if it doesn't auto-detect.)

Once everything above looks healthy, task #85 (Phase 7) is done. Tear the manual bring-up down before handing control to systemd, so you don't end up with two managers fighting over the same containers:

```bash
ssh wise150@192.168.1.16 "cd /opt/bonbon/current && docker compose -f deployment/compose/docker-compose.pi2.yml down"
```

---

## 5. Phase 13 — install the systemd units

8 unit files exist under `deployment/systemd/pi2/`, one per service (no units for `dashboard-api`/`dashboard-web` — intentional, they're test/dev-only and meant to be started manually per §4 above):

```
bonbon-pi2-hal.service
bonbon-pi2-asr.service
bonbon-pi2-vision.service
bonbon-pi2-perception-fusion.service
bonbon-pi2-llm.service
bonbon-pi2-behavior-engine.service
bonbon-pi2-tts.service
bonbon-pi2-distributed-liveness.service
```

Install and enable them:

```bash
ssh wise150@192.168.1.16 bash -s <<'EOF'
set -euo pipefail
sudo cp /opt/bonbon/current/deployment/systemd/pi2/*.service /etc/systemd/system/
sudo systemctl daemon-reload

for unit in bonbon-pi2-hal bonbon-pi2-asr bonbon-pi2-vision bonbon-pi2-perception-fusion \
            bonbon-pi2-llm bonbon-pi2-behavior-engine bonbon-pi2-tts bonbon-pi2-distributed-liveness; do
  sudo systemctl enable "$unit"
done
EOF
```

Start them (same order as the manual bring-up, so any failure is easy to attribute):

```bash
ssh wise150@192.168.1.16 bash -s <<'EOF'
set -euo pipefail
for unit in bonbon-pi2-hal bonbon-pi2-asr bonbon-pi2-vision bonbon-pi2-perception-fusion \
            bonbon-pi2-llm bonbon-pi2-behavior-engine bonbon-pi2-tts bonbon-pi2-distributed-liveness; do
  echo "--- starting $unit ---"
  sudo systemctl start "$unit"
  sleep 3
  sudo systemctl status "$unit" --no-pager -l | head -15
done
EOF
```

Each unit is `Type=oneshot`/`RemainAfterExit=yes` (it just runs `docker compose up -d <service>` and exits 0) — `systemctl status` will show `active (exited)`, which is correct, not a failure. What matters is the underlying container:

```bash
ssh wise150@192.168.1.16 "cd /opt/bonbon/current && docker compose -f deployment/compose/docker-compose.pi2.yml ps"
```

---

## 6. Phase 14 — final verification

```bash
# All 8 containers up, none restarting
ssh wise150@192.168.1.16 "cd /opt/bonbon/current && docker compose -f deployment/compose/docker-compose.pi2.yml ps"

# All 8 systemd units enabled + active
ssh wise150@192.168.1.16 "systemctl is-enabled bonbon-pi2-hal bonbon-pi2-asr bonbon-pi2-vision bonbon-pi2-perception-fusion bonbon-pi2-llm bonbon-pi2-behavior-engine bonbon-pi2-tts bonbon-pi2-distributed-liveness"
ssh wise150@192.168.1.16 "systemctl is-active bonbon-pi2-hal bonbon-pi2-asr bonbon-pi2-vision bonbon-pi2-perception-fusion bonbon-pi2-llm bonbon-pi2-behavior-engine bonbon-pi2-tts bonbon-pi2-distributed-liveness"

# ROS2 graph is real and complete
ssh wise150@192.168.1.16 "docker exec \$(docker compose -f /opt/bonbon/current/deployment/compose/docker-compose.pi2.yml ps -q hal) bash -lc 'source /opt/ros/humble/setup.bash && source /opt/bonbon/install/setup.bash && ros2 node list'"

# No crash-loop restarts since boot (RestartCount stays at 0)
ssh wise150@192.168.1.16 "docker inspect --format='{{.Name}}: RestartCount={{.RestartCount}}' \$(docker compose -f /opt/bonbon/current/deployment/compose/docker-compose.pi2.yml ps -q)"

# Thermal sanity (compare against the 48.3C idle baseline in PI2_RASPBERRY_PI_PREFLIGHT_REPORT.md)
ssh wise150@192.168.1.16 "vcgencmd measure_temp && vcgencmd get_throttled"

# Reboot survival test (systemd units are enabled — confirm they come back after a real reboot)
ssh wise150@192.168.1.16 "sudo reboot"
# wait ~60s, then:
ssh wise150@192.168.1.16 "cd /opt/bonbon/current && docker compose -f deployment/compose/docker-compose.pi2.yml ps"
```

If everything above is green, tasks #85 and #86 are complete and this is a real, verified, systemd-managed Pi-2 deployment — not just "it built."

---

## Known gaps this doc does not paper over

- No image registry exists in this repo — `BONBON_IMAGE_TAG` is a locally-built tag, not something `docker compose pull` can fetch on another machine. If you rebuild after a code change, you must re-run §3 with a new `VERSION` and update `/etc/bonbon/bonbon.env` + `/opt/bonbon/current`'s symlink target to match (same rollback pattern as `deployment/docs/rollback_process.md`).
- `devops/scripts/deploy_to_robot.sh` (the repo's one existing automated deploy script) only knows about `docker-compose.robot.yml` (the single-machine deployment) — it has no concept of the 3-Pi split or `docker-compose.pi2.yml`. The commands above are manual precisely because that automation doesn't cover this path yet; wiring Pi-2/Pi-3 into `deploy_to_robot.sh` is a real follow-up, not done here.
- No OAK-D Lite / ReSpeaker XVF3800 was physically attached to this Pi-2 unit as of `docs/PI2_HARDWARE_CHECK_REPORT.md` — `hal`, `asr`, `vision`, `tts` will start, but will honestly report degraded/hardware-unavailable mode via `bonbon_hal`'s `DriverFault` path until the real peripherals are connected. That is expected behavior, not a bug to chase during this bring-up.
