#!/bin/bash
# scripts/pi2/install_pi2_system_dependencies.sh
#
# Host-side system dependencies for Pi-2 (Human AI). Deliberately NOT a
# bare-metal ROS2 Humble install: this Pi runs Debian 13 "trixie" with
# Python 3.13, which ROS2 Humble's official apt packages do not target
# (they're built for Ubuntu 22.04 Jammy / Python 3.10). Forcing Humble
# onto trixie would mean mixed apt sources or manual .deb extraction --
# fragile and unsupported. Instead, ROS2 runs inside the `bonbon/ai`
# Docker image (built FROM ros:humble-ros-base-jammy), so the ROS2
# runtime always gets its officially-supported OS regardless of what the
# host is running. See docs/PI2_RASPBERRY_PI_PREFLIGHT_REPORT.md for the
# full reasoning.
#
# This script therefore only installs what the HOST itself needs:
# Docker Engine + Compose plugin (to run the container stack), Ollama
# (runs natively -- no reason to containerize a model server), and a
# handful of diagnostic tools used by scripts/pi2/check_pi2_hardware.sh.
#
# Idempotent: safe to re-run. Checks before installing, never blindly
# reinstalls or downgrades an existing tool.

set -euo pipefail

log() { echo "[install_pi2_system_dependencies] $*"; }

# ── Docker Engine + Compose plugin ──────────────────────────────────────────
if command -v docker >/dev/null 2>&1; then
    log "Docker already installed: $(docker --version)"
else
    log "Installing Docker Engine via get.docker.com convenience script..."
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    log "Docker installed: $(docker --version)"
    log "NOTE: you were added to the 'docker' group -- log out/in (or start a new SSH"
    log "session) for that to take effect without needing sudo for docker commands."
fi

if docker compose version >/dev/null 2>&1; then
    log "Docker Compose plugin already present: $(docker compose version)"
else
    log "ERROR: 'docker compose' plugin not found after Docker install." >&2
    log "get.docker.com normally includes it -- check the Docker install log above." >&2
    exit 1
fi

# ── Ollama (native host install -- not containerized) ───────────────────────
if command -v ollama >/dev/null 2>&1; then
    log "Ollama already installed: $(ollama --version)"
else
    log "Installing Ollama via ollama.com convenience script..."
    curl -fsSL https://ollama.com/install.sh | sh
    log "Ollama installed: $(ollama --version)"
fi

# ── Diagnostic tools used by check_pi2_hardware.sh ──────────────────────────
NEEDED_PKGS=()
command -v lsusb    >/dev/null 2>&1 || NEEDED_PKGS+=(usbutils)
command -v arecord   >/dev/null 2>&1 || NEEDED_PKGS+=(alsa-utils)
command -v v4l2-ctl >/dev/null 2>&1 || NEEDED_PKGS+=(v4l-utils)
command -v vcgencmd  >/dev/null 2>&1 || true  # Raspberry Pi firmware tool, already present per preflight

if [ "${#NEEDED_PKGS[@]}" -gt 0 ]; then
    log "Installing missing diagnostic packages: ${NEEDED_PKGS[*]}"
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends "${NEEDED_PKGS[@]}"
else
    log "All diagnostic tools already present."
fi

log "Done."
