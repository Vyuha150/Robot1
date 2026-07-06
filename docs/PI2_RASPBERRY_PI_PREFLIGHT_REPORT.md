# Pi-2 Raspberry Pi Preflight Report

Generated: 2026-07-06. Target: `wise150@192.168.1.16` (hostname `Wise150`), reached via SSH key auth (no password used or stored).

## Summary verdict: PROCEED, with one architecture decision required before Phase 5+

The board itself is healthy (plenty of RAM/disk/thermal headroom). The blocking issue is **not**
resource shortage — it's that the installed OS (Debian 13 "trixie", Python 3.13) is not a platform
ROS2 Humble ships official binaries for. This must be resolved with a deliberate choice (see
"Decision required" below) before installing anything ROS2-related. Nothing has been installed yet.

## Raw findings

| Check | Result | Assessment |
|---|---|---|
| Model | Raspberry Pi 5 Model B Rev 1.1 | Matches BOM exactly |
| OS | Debian GNU/Linux 13 (trixie), kernel `6.18.34+rpt-rpi-2712` | 64-bit — good. **Not Ubuntu 22.04/24.04** — see decision below |
| Architecture | aarch64 | OK — no 32-bit compatibility risk |
| RAM | 7.9 GiB total, 7.4 GiB available | Healthy, no pressure |
| Disk | 29 GB total, 23 GB available (19% used) | Healthy, ample room for Docker images/models |
| Temperature | 48.3°C | Normal idle temp, nowhere near throttle threshold |
| Throttling | `throttled=0x0` | None — no under-voltage/thermal events recorded |
| Python | 3.13.5 | Newer than ROS2 Humble's target (3.10) or even Jazzy's (3.12) — see decision below |
| ROS2 | **not installed** (`ros2: command not found`) | Expected on a fresh board |
| Ollama | **not installed** | Expected |
| Docker | **not installed** | Expected |
| Hailo (`hailortcli`) | **not installed** | AI HAT+2 present per BOM but runtime not yet set up — matches existing "present, not yet integrated" status in `config/distributed/pi_human_ai.yaml` |
| USB peripherals | Only root hubs enumerate — **no OAK-D Lite, no ReSpeaker detected** | Camera/mic are not physically connected to this board right now. Software will come up in honest "hardware unavailable" degraded mode until they're plugged in — this is expected/by-design, not an error |
| Network | `wlan0` up at 192.168.1.16 (Wi-Fi); `eth0` down/no-carrier | Working, but Wi-Fi is less deterministic than wired Ethernet for ROS2 DDS traffic between Pis. Not blocking; worth wiring Ethernet before final multi-Pi integration testing |
| Time sync | `System clock synchronized: yes`, NTP active, IST timezone | Healthy — matters for distributed heartbeat/log correlation across Pis |

## Decision required: how do we run ROS2 Humble on this OS?

Debian 13 (trixie) ships Python 3.13. ROS2 Humble's official apt packages are built against
Ubuntu 22.04 Jammy + Python 3.10 and are not available for trixie — a plain
`apt install ros-humble-desktop` will not work here, and forcing it (mixed apt sources, manual
`.deb` extraction) would be fragile, unsupported, and exactly the kind of "lightweight shortcut"
we're avoiding.

**Recommendation: use the Docker-based deployment already built this session
(`deployment/compose/docker-compose.pi2.yml` + `Dockerfile.ros2`/`Dockerfile.ai`), not a bare-metal
ROS2 install.** The container images are built on Ubuntu 22.04, so ROS2 Humble runs in its
officially-supported environment regardless of the host OS. This is a strictly better fit than
building ROS2 from source on-device (multi-hour build, ongoing maintenance burden) or introducing a
second, parallel bare-metal install path alongside the Docker path that already exists —
that would be the redundancy this deployment is explicitly trying to avoid.

This means Phase 5/6/7 of the deployment (system deps, Python venv, `colcon build`) run **inside
the container image**, not on the Debian 13 host. The host only needs: Docker Engine + Compose
plugin (well-supported on Debian 13/aarch64 via Docker's official apt repo), plus whatever the host
itself must own directly (USB device access rules for OAK-D/ReSpeaker passthrough into the
container, NTP/chrony, Ollama — see below).

**Ollama exception:** Ollama runs natively on the host (there's no reason to containerize a model
runtime that just needs to serve HTTP on localhost, and it has direct official Debian/arm64
support) — so Ollama + `qwen2.5:0.5b` are installed directly on the Pi, while the ROS2/Python AI
stack (vision, ASR, LLM gateway, TTS, perception fusion) runs in the Pi-2 container per the
existing compose file.

I'm proceeding on this basis unless you'd rather force a bare-metal ROS2 build — flag now if so.

## Not yet checked (deferred to later phases)
- OAK-D Lite / ReSpeaker functional test — impossible until physically connected; will report
  honestly as BLOCKED (hardware absent) in Phase 9 until then.
- AI HAT+2/Hailo runtime — deferred; BOM confirms hardware presence, integration is a known,
  previously-flagged gap (Phase 10 of the original 14-phase brief), out of scope for this
  deployment pass unless requested separately.
