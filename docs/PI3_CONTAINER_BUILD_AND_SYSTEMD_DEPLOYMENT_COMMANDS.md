# Pi-3 Container Build, Compose Bring-Up, and systemd Deployment — Exact Commands

**Honesty note up front, same as the Pi-1 equivalent doc:** Pi-2 went
through a real hardware preflight/transfer/hardware-check pass before its
command doc was written. **No such pass has ever been run against a real
Pi-3 unit.** Everything below is derived from the real, reviewed artifacts
already in this repo (`deployment/compose/docker-compose.pi3.yml`,
`deployment/docker/Dockerfile.navigation`, `deployment/systemd/pi3/*.service`)
— it has never been executed against physical Pi-3 hardware. Pi-3's own
compose file already flags two real, unresolved hardware risks in its own
header comments (device-path stability for the USB-serial LiDAR/motor
controller, and GID values for the `gpio`/`i2c` groups) — both are
repeated below, not silently assumed away.

Target per `config/distributed/robot_network.yaml`: hostname `bonbon-pi3`,
static IP `192.168.10.13` (role `navigation_safety`). Confirmed BOM: Pi 5 +
AI HAT+2, Cytron SmartDrive MDDS30 + Rhino 24V 60RPM motors, SLAMTEC
RPLiDAR A2M12, 2x NEMA17 closed-loop steppers, 3x 25kgcm PWM servos.

---

## 0. Prerequisites

```bash
ssh <user>@<pi3-current-address> "echo CONNECTED && hostname"
```

## 1. Before anything else: resolve the USB-serial device-path risk

**Do this before Step 2, on the real hardware, before relying on any
command below.** `docker-compose.pi3.yml` hardcodes `/dev/ttyUSB0`
(RPLiDAR) and `/dev/ttyUSB1` (Cytron MDDS30 motor driver) — raw USB-serial
enumeration order is **not guaranteed stable** across reboots or hub
re-plugs. If they swap, the lidar and drive motors silently swap control
paths, which is a genuine safety hazard for the motor half.

```bash
# On the Pi, with both devices connected:
ssh bonbon-pi3 "udevadm info -a -n /dev/ttyUSB0 | grep -E 'idVendor|idProduct|serial' | head -5"
ssh bonbon-pi3 "udevadm info -a -n /dev/ttyUSB1 | grep -E 'idVendor|idProduct|serial' | head -5"
```

Write a udev rule mapping each device's real vendor:product (and serial,
if exposed) to a stable symlink (`/dev/bonbon-lidar`, `/dev/bonbon-motor`),
e.g. `/etc/udev/rules.d/99-bonbon-serial.rules`:

```
SUBSYSTEM=="tty", ATTRS{idVendor}=="<lidar-vendor>", ATTRS{idProduct}=="<lidar-product>", SYMLINK+="bonbon-lidar"
SUBSYSTEM=="tty", ATTRS{idVendor}=="<motor-vendor>", ATTRS{idProduct}=="<motor-product>", SYMLINK+="bonbon-motor"
```

Then reload udev (`sudo udevadm control --reload-rules && sudo udevadm trigger`)
and update `docker-compose.pi3.yml`'s `hal` service device paths from
`/dev/ttyUSB0`/`/dev/ttyUSB1` to `/dev/bonbon-lidar`/`/dev/bonbon-motor`
before building/transferring in Step 2. This doc cannot fill in the real
vendor:product IDs for you — they come from the physical hardware.

## 2. Bootstrap the network

```bash
scp devops/scripts/bootstrap_pi_network.py <user>@<pi3-current-address>:~/
scp -r config/distributed <user>@<pi3-current-address>:~/robot_network_config

sudo python3 bootstrap_pi_network.py --role pi3 --network-config ~/robot_network_config/robot_network.yaml
# review the DRY RUN plan, then:
sudo python3 bootstrap_pi_network.py --role pi3 --network-config ~/robot_network_config/robot_network.yaml --apply
```

## 3. Transfer the code

```bash
git archive --format=tar.gz -o deploy/pi3_deployment_bundle.tar.gz HEAD \
  ros2_ws/src/bonbon_safety ros2_ws/src/bonbon_hal ros2_ws/src/bonbon_base_controller \
  ros2_ws/src/bonbon_actuation ros2_ws/src/bonbon_motion_approval_gateway \
  ros2_ws/src/bonbon_navigation ros2_ws/src/bonbon_distributed_safety \
  ros2_ws/src/bonbon_authority_manager ros2_ws/src/bonbon_navigation_bringup \
  ros2_ws/src/bonbon_distributed_network_monitor ros2_ws/src/bonbon_msgs ros2_ws/src/bonbon_srvs \
  config deployment/docker/Dockerfile.navigation \
  deployment/compose/docker-compose.pi3.yml deployment/systemd/pi3 \
  devops/scripts/health_check.sh devops/scripts/pi_systemd_manager.py

ssh bonbon-pi3 "mkdir -p ~/bonbon_robot"
scp deploy/pi3_deployment_bundle.tar.gz bonbon-pi3:~/bonbon_robot/
ssh bonbon-pi3 "cd ~/bonbon_robot && tar xzf pi3_deployment_bundle.tar.gz && rm pi3_deployment_bundle.tar.gz"
```

(If you wrote a udev-symlink fix to `docker-compose.pi3.yml` in Step 1,
transfer that edited file instead of the checked-in one, or edit it
in-place on the Pi under `~/bonbon_robot/deployment/compose/docker-compose.pi3.yml`
before proceeding.)

## 4. Lay out the release directory + provision config

```bash
ssh bonbon-pi3 bash -s <<'EOF'
set -euo pipefail
VERSION="pi3-$(date +%Y%m%d-%H%M)"
sudo mkdir -p "/opt/bonbon/releases/$VERSION"
sudo cp -r ~/bonbon_robot/. "/opt/bonbon/releases/$VERSION/"
sudo ln -sfn "/opt/bonbon/releases/$VERSION" /opt/bonbon/current
sudo mkdir -p /etc/bonbon /var/log/bonbon /var/lib/bonbon /opt/bonbon/maps
echo "$VERSION" > /tmp/bonbon_pi3_version.txt
EOF

ssh bonbon-pi3 bash -s <<EOF
set -euo pipefail
VERSION=\$(cat /tmp/bonbon_pi3_version.txt)
sudo tee /etc/bonbon/bonbon.env >/dev/null <<ENV
BONBON_IMAGE_TAG=\$VERSION
ENV
sudo chmod 0640 /etc/bonbon/bonbon.env
EOF
```

No dashboard/JWT secrets needed here — Pi-3 runs no operator-facing API,
only ROS2 safety/navigation/actuation nodes.

## 5. Verify the `gpio`/`i2c` group GIDs before building

`Dockerfile.navigation` hardcodes GIDs 986/988 for the `gpio`/`i2c` groups,
copied from Pi-2's actual `/etc/group` — **explicitly flagged in the
Dockerfile's own comment as NOT yet verified against a real Pi-3 unit.**
Check before building:

```bash
ssh bonbon-pi3 "getent group gpio i2c dialout"
```

If the GIDs differ from 986/988, edit the `groupadd -g <gid> gpio` /
`i2c` lines in `deployment/docker/Dockerfile.navigation` on the Pi (under
`~/bonbon_robot/deployment/docker/Dockerfile.navigation`) to match before
building.

## 6. Build the image

```bash
ssh bonbon-pi3 bash -s <<'EOF'
set -euo pipefail
VERSION=$(cat /tmp/bonbon_pi3_version.txt)
cd /opt/bonbon/current
docker build -f deployment/docker/Dockerfile.navigation -t "bonbon/navigation:$VERSION" .
docker images bonbon/navigation
EOF
```

Recompiles the full navigation/safety/actuation ROS2 workspace (including
`ros-humble-navigation2`, `nav2-bringup`, `rtabmap-slam`) — expect
20-40+ minutes on a Pi 5, similar order to Pi-2's `Dockerfile.ai`.

## 7. Bring the stack up manually and verify

Bring `safety` up first and confirm it survives before anything else —
it's the highest-priority service on this Pi (`oom_score_adj: -900`,
`cpu_shares: 4096`, same protection tier as `docker-compose.robot.yml`'s
single-machine safety service):

```bash
ssh bonbon-pi3 bash -s <<'EOF'
set -euo pipefail
cd /opt/bonbon/current
export BONBON_IMAGE_TAG=$(cat /tmp/bonbon_pi3_version.txt)

for svc in safety hal base-controller actuation motion-gateway navigation distributed-liveness; do
  echo "--- bringing up $svc ---"
  docker compose -f deployment/compose/docker-compose.pi3.yml up -d "$svc"
  sleep 5
  docker compose -f deployment/compose/docker-compose.pi3.yml ps "$svc"
done
EOF
```

Confirm every container is `Up`, not `Restarting`. If `hal` crash-loops,
check the LiDAR/motor device paths first (Step 1) before anything else —
that's the most likely real-hardware failure mode this doc can't rule out
in advance.

```bash
ssh bonbon-pi3 "cd /opt/bonbon/current && docker compose -f deployment/compose/docker-compose.pi3.yml ps"

# ROS2 graph sanity check (from the safety container, network_mode: host):
ssh bonbon-pi3 "docker exec \$(docker compose -f /opt/bonbon/current/deployment/compose/docker-compose.pi3.yml ps -q safety) bash -lc 'source /opt/ros/humble/setup.bash && source /opt/bonbon/install/setup.bash && ros2 node list && ros2 topic list'"
```

Once healthy, tear the manual bring-up down before handing control to systemd:

```bash
ssh bonbon-pi3 "cd /opt/bonbon/current && docker compose -f deployment/compose/docker-compose.pi3.yml down"
```

## 8. Install and start the systemd units

7 units, real `Requires=` chain already encoded (`safety` → `hal` →
`actuation`/`motion-gateway`; `hal` + `base-controller` → `navigation`):

```bash
# Plan (no changes):
ssh bonbon-pi3 "cd /opt/bonbon/current && python3 devops/scripts/pi_systemd_manager.py --role pi3"

# Install + enable:
ssh bonbon-pi3 "cd /opt/bonbon/current && sudo python3 devops/scripts/pi_systemd_manager.py --role pi3 --apply"

# Install + enable + start, in dependency order:
ssh bonbon-pi3 "cd /opt/bonbon/current && sudo python3 devops/scripts/pi_systemd_manager.py --role pi3 --apply --start"
```

## 9. Final verification

```bash
ssh bonbon-pi3 "cd /opt/bonbon/current && docker compose -f deployment/compose/docker-compose.pi3.yml ps"
ssh bonbon-pi3 "cd /opt/bonbon/current && python3 devops/scripts/pi_systemd_manager.py --role pi3 --verify"

# No crash-loop restarts since boot -- especially watch `safety` and `hal`:
ssh bonbon-pi3 "docker inspect --format='{{.Name}}: RestartCount={{.RestartCount}}' \$(docker compose -f /opt/bonbon/current/deployment/compose/docker-compose.pi3.yml ps -q)"

# Thermal sanity (Pi 5 + AI HAT+2 under nav2/SLAM load runs hotter than idle):
ssh bonbon-pi3 "vcgencmd measure_temp && vcgencmd get_throttled"

# Reboot survival test:
ssh bonbon-pi3 "sudo reboot"
# wait ~60s, then:
ssh bonbon-pi3 "cd /opt/bonbon/current && docker compose -f deployment/compose/docker-compose.pi3.yml ps"
```

## Known gaps this doc does not paper over

- Never run against real Pi-3 hardware.
- USB-serial device-path stability (Step 1) is an open risk until real
  vendor:product IDs are captured from the physical LiDAR/motor
  controller and a udev rule is written.
- `gpio`/`i2c` GIDs (Step 5) are copied from Pi-2's fleet image, not
  independently confirmed for Pi-3.
- No AI HAT+2/Hailo inference runs on Pi-3 in this compose file yet — per
  `docs/HAILO_RUNTIME_INTEGRATION_REPORT.md`, on-device Hailo integration
  is software-complete/mock-tested but has never run on real Hailo
  hardware anywhere in this fleet (Pi-2 or Pi-3).
