# Pi-1 Container Build, Compose Bring-Up, and systemd Deployment — Exact Commands

**Honesty note up front, unlike the equivalent Pi-2 doc:** Pi-2 went
through a real hardware preflight/transfer/hardware-check pass
(`docs/PI2_RASPBERRY_PI_PREFLIGHT_REPORT.md` and siblings) before its
command doc was written. **No such pass has ever been run against a real
Pi-1 unit.** Everything below is derived directly from the real, reviewed
artifacts already in this repo (`deployment/compose/docker-compose.pi1.yml`,
`deployment/docker/Dockerfile.dashboard`, `Dockerfile.ros2`,
`deployment/systemd/pi1/*.service`) — it has never been executed against
physical Pi-1 hardware. Some Pi-2-specific bugs already found and fixed on
real hardware (the `/dev/gpiomem0` path, single-element `command:` lists,
subshell-per-job sourcing) were pre-emptively applied to Pi-1's artifacts
too where the same pattern appears, but Pi-1 has no HAL/GPIO hardware at
all (plain Pi 5 + touchscreen, no AI HAT) — so most of those Pi-2 hardware
gotchas don't apply here in the first place. Run this yourself on real
Pi-1 hardware and treat any divergence as real, new information, not a bug
in this doc.

Target per `config/distributed/robot_network.yaml`: hostname `bonbon-pi1`,
static IP `192.168.10.11` (role `ui_api`). This doc assumes you can already
reach the physical Pi-1 unit at *some* address (its current DHCP address,
or directly via keyboard/monitor) — that address is not known to this repo
and must come from you (check your router's DHCP client list, or
`ip addr` on the Pi directly).

---

## 0. Prerequisites

```bash
# From your workstation, repo root -- confirm the target is reachable at
# whatever its CURRENT address is (not yet the final static IP below):
ssh <user>@<pi1-current-address> "echo CONNECTED && hostname"
```

## 1. Bootstrap the network (static IP, ROS_DOMAIN_ID, chrony)

```bash
# Transfer just the bootstrap script + configs it needs (small, no code build yet):
scp devops/scripts/bootstrap_pi_network.py <user>@<pi1-current-address>:~/
scp -r config/distributed <user>@<pi1-current-address>:~/robot_network_config

# On the Pi (or via ssh <user>@<pi1-current-address> "..."):
sudo python3 bootstrap_pi_network.py --role pi1 --network-config ~/robot_network_config/robot_network.yaml
# review the printed DRY RUN plan, then:
sudo python3 bootstrap_pi_network.py --role pi1 --network-config ~/robot_network_config/robot_network.yaml --apply
```

After this, the Pi's hostname is `bonbon-pi1`, its static IP is
`192.168.10.11`, and `/etc/bonbon/bonbon.env` has `ROS_DOMAIN_ID`/
`RMW_IMPLEMENTATION`/`CYCLONEDDS_URI` set. From here on, reference the Pi
as `bonbon-pi1` (once your workstation can resolve it — otherwise keep
using the static IP directly).

## 2. Transfer the code

```bash
# From your workstation, repo root:
git archive --format=tar.gz -o deploy/pi1_deployment_bundle.tar.gz HEAD \
  ros2_ws/src/bonbon_operator_api ros2_ws/src/bonbon_fault_manager \
  ros2_ws/src/bonbon_distributed_safety ros2_ws/src/bonbon_authority_manager \
  ros2_ws/src/bonbon_distributed_network_monitor ros2_ws/src/bonbon_msgs ros2_ws/src/bonbon_srvs \
  config deployment/docker/Dockerfile.dashboard deployment/docker/Dockerfile.ros2 \
  deployment/compose/docker-compose.pi1.yml deployment/systemd/pi1 \
  devops/scripts/health_check.sh devops/scripts/pi_systemd_manager.py \
  devops/scripts/launch_kiosk.sh

ssh bonbon-pi1 "mkdir -p ~/bonbon_robot"
scp deploy/pi1_deployment_bundle.tar.gz bonbon-pi1:~/bonbon_robot/
ssh bonbon-pi1 "cd ~/bonbon_robot && tar xzf pi1_deployment_bundle.tar.gz && rm pi1_deployment_bundle.tar.gz"
```

## 3. Lay out the release directory + provision secrets

Same `/opt/bonbon/releases/<version>` + `/opt/bonbon/current` convention
as every other Pi (`deployment/docs/deployment_notes.md`).

```bash
ssh bonbon-pi1 bash -s <<'EOF'
set -euo pipefail
VERSION="pi1-$(date +%Y%m%d-%H%M)"
sudo mkdir -p "/opt/bonbon/releases/$VERSION"
sudo cp -r ~/bonbon_robot/. "/opt/bonbon/releases/$VERSION/"
sudo ln -sfn "/opt/bonbon/releases/$VERSION" /opt/bonbon/current
sudo mkdir -p /etc/bonbon /var/log/bonbon /var/lib/bonbon
echo "$VERSION" > /tmp/bonbon_pi1_version.txt
EOF
```

Pi-1 hosts the **real, production** dashboard-api (unlike Pi-2's
test-mode-only copy) — it needs real secrets, not `BONBON_TEST_MODE=1`:

```bash
ssh bonbon-pi1 bash -s <<EOF
set -euo pipefail
VERSION=\$(cat /tmp/bonbon_pi1_version.txt)
JWT_SECRET=\$(openssl rand -hex 32)
ADMIN_PASSWORD=\$(openssl rand -base64 18)
sudo tee /etc/bonbon/bonbon.env >/dev/null <<ENV
BONBON_IMAGE_TAG=\$VERSION
BONBON_JWT_SECRET=\$JWT_SECRET
BONBON_ADMIN_PASSWORD=\$ADMIN_PASSWORD
ENV
sudo chmod 0640 /etc/bonbon/bonbon.env
echo "Admin password (save this now, it is not printed again): \$ADMIN_PASSWORD"
EOF
```

**Save the printed admin password immediately** — this command does not
persist it anywhere else on your workstation.

## 4. Build the images

```bash
ssh bonbon-pi1 bash -s <<'EOF'
set -euo pipefail
VERSION=$(cat /tmp/bonbon_pi1_version.txt)
cd /opt/bonbon/current
docker build -f deployment/docker/Dockerfile.dashboard -t "bonbon/dashboard:$VERSION" .
docker build -f deployment/docker/Dockerfile.ros2 -t "bonbon/ros2:$VERSION" .
docker images | grep bonbon
EOF
```

`Dockerfile.dashboard` is lightweight (`python:3.11-slim`, no ROS2) —
expect a couple of minutes. `Dockerfile.ros2` recompiles the ROS2
workspace — expect 15-30+ minutes on a Pi 5, similar to Pi-2's `Dockerfile.ai`.

**Known, documented limitation** (from `docker-compose.pi1.yml`'s own
header comment, not introduced here): the lightweight `dashboard-api`
container has no rclpy, so its ROS2 bridge is inert inside Docker
(`_ROS2_AVAILABLE=False`) — it will serve the dashboard UI/API but won't
see live robot state until either a network-facing ROS2↔HTTP bridge is
built, or it's run bare-metal via `ros2 launch bonbon_ui_api_bringup
ui_api_bringup.launch.py` instead of this split-container setup. This
doc deploys the split-container form as-is; fixing that gap is a
separate, not-yet-scoped decision.

## 5. Bring the stack up manually and verify

```bash
ssh bonbon-pi1 bash -s <<'EOF'
set -euo pipefail
cd /opt/bonbon/current
export BONBON_IMAGE_TAG=$(cat /tmp/bonbon_pi1_version.txt)

for svc in dashboard-api ros2-support; do
  echo "--- bringing up $svc ---"
  docker compose -f deployment/compose/docker-compose.pi1.yml up -d "$svc"
  sleep 5
  docker compose -f deployment/compose/docker-compose.pi1.yml ps "$svc"
done
EOF
```

Confirm both stayed up (not `Restarting`), and check the dashboard responds:

```bash
curl -s http://192.168.10.11:8080/health
# From any machine on the LAN, open http://192.168.10.11:8080 in a browser.
```

Confirm the ROS2-only side (`ros2-support`) actually launched
`fault_manager` + `distributed_safety_node` + `authority_manager_node` +
`network_monitor_node`:

```bash
ssh bonbon-pi1 "docker exec \$(docker compose -f /opt/bonbon/current/deployment/compose/docker-compose.pi1.yml ps -q ros2-support) bash -lc 'source /opt/ros/humble/setup.bash && source /opt/bonbon/install/setup.bash && ros2 node list'"
```

Expect to see `fault_manager_node`, `distributed_safety_node`,
`authority_manager_node`, `network_monitor_node` — **not** a second
`operator_api_node`/dashboard node (that would mean the split-container
design broke and both containers are racing for port 8080; see the
module comment in `docker-compose.pi1.yml` for why they're deliberately
separate).

Once healthy, tear the manual bring-up down before handing control to
systemd:

```bash
ssh bonbon-pi1 "cd /opt/bonbon/current && docker compose -f deployment/compose/docker-compose.pi1.yml down"
```

## 6. Install and start the systemd units

Pi-1 has 3 units: `bonbon-pi1-dashboard-api.service`,
`bonbon-pi1-ros2-support.service` (both `docker compose up -d <service>`,
same pattern as every other Pi), and `bonbon-pi1-dashboard-frontend.service`
(a **native**, non-Docker unit that launches the touchscreen kiosk browser
via `scripts/launch_kiosk.sh` — `Requires=bonbon-pi1-dashboard-api.service`,
so it won't launch before the API it renders can respond).

Use `devops/scripts/pi_systemd_manager.py` (built this pass, computes the
correct install/start order from each unit's own `Requires=`/`After=`
graph instead of a hand-typed sequence):

```bash
# See the plan first (no changes):
ssh bonbon-pi1 "cd /opt/bonbon/current && python3 devops/scripts/pi_systemd_manager.py --role pi1"

# Install + enable:
ssh bonbon-pi1 "cd /opt/bonbon/current && sudo python3 devops/scripts/pi_systemd_manager.py --role pi1 --apply"

# Install + enable + start, in dependency order:
ssh bonbon-pi1 "cd /opt/bonbon/current && sudo python3 devops/scripts/pi_systemd_manager.py --role pi1 --apply --start"
```

**Note on the kiosk unit**: `bonbon-pi1-dashboard-frontend.service`
`Wants=graphical.target` and sets `DISPLAY=:0` — it only makes sense on a
Pi actually booted to a desktop session with the touchscreen attached.
Headless testing/CI Pi-1 units should expect this one unit to fail to
start (no `graphical.target`/`DISPLAY`) while the two Docker-backed units
succeed — that's expected, not a deployment bug.

## 7. Final verification

```bash
# Containers up, not restarting:
ssh bonbon-pi1 "cd /opt/bonbon/current && docker compose -f deployment/compose/docker-compose.pi1.yml ps"

# All units enabled/active (kiosk unit excluded if headless -- see note above):
ssh bonbon-pi1 "cd /opt/bonbon/current && python3 devops/scripts/pi_systemd_manager.py --role pi1 --verify"

# Dashboard reachable from the LAN:
curl -s http://192.168.10.11:8080/health

# No crash-loop restarts since boot:
ssh bonbon-pi1 "docker inspect --format='{{.Name}}: RestartCount={{.RestartCount}}' \$(docker compose -f /opt/bonbon/current/deployment/compose/docker-compose.pi1.yml ps -q)"

# Reboot survival test:
ssh bonbon-pi1 "sudo reboot"
# wait ~60s, then:
ssh bonbon-pi1 "cd /opt/bonbon/current && docker compose -f deployment/compose/docker-compose.pi1.yml ps"
```

## Known gaps this doc does not paper over

- Never run against real Pi-1 hardware (see the honesty note at the top).
- The dashboard-api-inside-Docker ROS2-bridge gap (Step 4) is real and
  pre-existing, not fixed here.
- `bonbon-fault*` has no dedicated systemd unit — by design, it's bundled
  into `bonbon-pi1-ros2-support.service` alongside the other Pi-1-only
  ROS2 nodes (`docs/THREE_PI_ROS2_NODE_GRAPH.md` documents
  `fault_manager_node` as Pi-1-only: it aggregates `/bonbon/hal/fault`
  from Pi-2 and Pi-3 over the shared DDS domain, no bridging needed —
  running a second copy on Pi-2/Pi-3 would create duplicate, conflicting
  fault registries, not fill a gap).
