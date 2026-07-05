#!/usr/bin/env python3
"""Apply config/distributed/robot_network.yaml to THIS physical Pi.

Sets up everything the three-Pi deployment needs before any BonBon
service can start: static IP, hostname, shared ROS_DOMAIN_ID +
CycloneDDS unicast-peer profile, and chrony time sync (Pi-3 is the LAN
NTP server per robot_network.yaml's time_sync.server:pi3).

This is genuinely new -- nothing like it existed before this pass (the
per-Pi bringup/compose/systemd work assumed the network was already
correctly configured; this is what actually configures it).

Defaults to DRY RUN (prints every command it would run, changes
nothing) -- this script touches system-level networking, hostname, and
time sync on real hardware, so an accidental run must never silently
reconfigure a machine. Pass --apply to actually execute, and it must be
run as root at that point (networking/hostname/chrony all require it).

Usage:
    # Pi-2, see what would happen:
    sudo python3 devops/scripts/bootstrap_pi_network.py --role pi2

    # Pi-2, actually apply it:
    sudo python3 devops/scripts/bootstrap_pi_network.py --role pi2 --apply

    # Override the wired interface name (default: eth0):
    sudo python3 devops/scripts/bootstrap_pi_network.py --role pi3 --apply --interface enp1s0
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print(
        "PyYAML is required (pip install pyyaml / apt install python3-yaml)",
        file=sys.stderr,
    )
    sys.exit(2)

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_NETWORK_CONFIG = _ROOT / "config" / "distributed" / "robot_network.yaml"
_BONBON_ENV_PATH = Path("/etc/bonbon/bonbon.env")
_DDS_PROFILE_DEST = Path("/etc/bonbon/cyclonedds_ethernet_profile.xml")
_CHRONY_CONF = Path("/etc/chrony/chrony.conf")


class BootstrapError(RuntimeError):
    pass


def _load_network_config(path: Path) -> dict:
    if not path.exists():
        raise BootstrapError(f"network config not found: {path}")
    with open(path) as f:
        cfg = yaml.safe_load(f)
    for key in ("pis", "ros2", "time_sync"):
        if key not in cfg:
            raise BootstrapError(f"{path} is missing required section: {key}")
    return cfg


def _run(cmd: list[str], apply: bool) -> None:
    printable = " ".join(cmd)
    if not apply:
        print(f"[DRY RUN] {printable}")
        return
    print(f"[APPLY]   {printable}")
    subprocess.run(cmd, check=True)


def _write_file(path: Path, content: str, apply: bool) -> None:
    if not apply:
        print(f"[DRY RUN] write {path}:")
        for line in content.splitlines():
            print(f"    {line}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(f"[APPLY]   wrote {path}")


def _upsert_env_file(path: Path, updates: dict[str, str], apply: bool) -> None:
    """Merge key=value pairs into an existing env file without clobbering
    unrelated lines a previous deployment step may have already written
    (e.g. secrets, BONBON_DASHBOARD_PORT)."""
    existing: dict[str, str] = {}
    order: list[str] = []
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                existing[k] = v
                order.append(k)
    for k, v in updates.items():
        if k not in existing:
            order.append(k)
        existing[k] = v
    content = "\n".join(f"{k}={existing[k]}" for k in order) + "\n"
    _write_file(path, content, apply)


def _configure_static_ip(interface: str, static_ip: str, apply: bool) -> None:
    ip_iface = ipaddress.ip_interface(f"{static_ip}/24")
    con_name = f"bonbon-{interface}"
    # nmcli is Raspberry Pi OS Bookworm's default network manager (Pi 5's
    # shipped OS) -- dhcpcd-style /etc/dhcpcd.conf editing is the older
    # Bullseye-era approach and is NOT used here on purpose.
    _run(
        [
            "nmcli",
            "con",
            "add",
            "type",
            "ethernet",
            "con-name",
            con_name,
            "ifname",
            interface,
            "ip4",
            str(ip_iface),
        ],
        apply,
    )
    _run(["nmcli", "con", "modify", con_name, "ipv4.method", "manual"], apply)
    _run(["nmcli", "con", "up", con_name], apply)


def _configure_chrony(is_time_server: bool, server_ip: str, subnet: str, apply: bool) -> None:
    if not _CHRONY_CONF.parent.exists() and apply:
        raise BootstrapError(
            f"{_CHRONY_CONF.parent} does not exist -- is chrony installed? "
            "(sudo apt install chrony)"
        )
    if is_time_server:
        content = (
            "# Managed by devops/scripts/bootstrap_pi_network.py -- do not hand-edit.\n"
            "# This Pi is robot_network.yaml's time_sync.server -- serve NTP to the\n"
            "# other two Pis on the robot's private subnet only.\n"
            "pool pool.ntp.org iburst\n"
            f"allow {subnet}\n"
            "local stratum 10\n"
        )
    else:
        content = (
            "# Managed by devops/scripts/bootstrap_pi_network.py -- do not hand-edit.\n"
            f"server {server_ip} iburst prefer\n"
        )
    _write_file(_CHRONY_CONF, content, apply)
    _run(["systemctl", "restart", "chrony"], apply)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--role", required=True, choices=["pi1", "pi2", "pi3"])
    parser.add_argument("--network-config", type=Path, default=_DEFAULT_NETWORK_CONFIG)
    parser.add_argument("--interface", default="eth0", help="Wired interface name (default: eth0)")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually execute changes. Without this flag, only prints what would happen.",
    )
    args = parser.parse_args(argv)

    if args.apply and os.geteuid() != 0:
        print("--apply requires root (networking/hostname/chrony all need it)", file=sys.stderr)
        return 2

    try:
        cfg = _load_network_config(args.network_config)
    except BootstrapError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    pi_cfg = cfg["pis"].get(args.role)
    if pi_cfg is None:
        print(f"ERROR: role '{args.role}' not found in {args.network_config}", file=sys.stderr)
        return 1

    ros2_cfg = cfg["ros2"]
    time_cfg = cfg["time_sync"]
    hostname = pi_cfg["hostname"]
    static_ip = pi_cfg["static_ip"]
    dds_profile_src = _ROOT / ros2_cfg["dds_profile_file"]
    if not dds_profile_src.exists():
        print(f"ERROR: dds_profile_file not found: {dds_profile_src}", file=sys.stderr)
        return 1

    subnet = str(ipaddress.ip_network(f"{static_ip}/24", strict=False))
    time_server_role = time_cfg["server"]
    time_server_ip = cfg["pis"][time_server_role]["static_ip"]
    is_time_server = args.role == time_server_role

    print(f"== Bootstrapping network for {args.role} ({hostname}, {static_ip}) ==")
    if not args.apply:
        print("(dry run -- pass --apply, as root, to actually execute)\n")

    # 1. Hostname
    _run(["hostnamectl", "set-hostname", hostname], args.apply)

    # 2. Static IP via NetworkManager
    _configure_static_ip(args.interface, static_ip, args.apply)

    # 3. CycloneDDS unicast-peer profile
    if args.apply:
        _DDS_PROFILE_DEST.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(dds_profile_src, _DDS_PROFILE_DEST)
        print(f"[APPLY]   copied {dds_profile_src} -> {_DDS_PROFILE_DEST}")
    else:
        print(f"[DRY RUN] copy {dds_profile_src} -> {_DDS_PROFILE_DEST}")

    # 4. /etc/bonbon/bonbon.env -- shared ROS2 domain/RMW/DDS config every
    #    bonbon-*.service EnvironmentFile= line already reads.
    _upsert_env_file(
        _BONBON_ENV_PATH,
        {
            "ROS_DOMAIN_ID": str(ros2_cfg["ros_domain_id"]),
            "RMW_IMPLEMENTATION": ros2_cfg["rmw_implementation"],
            "CYCLONEDDS_URI": f"file://{_DDS_PROFILE_DEST}",
        },
        args.apply,
    )

    # 5. chrony time sync
    _configure_chrony(is_time_server, time_server_ip, subnet, args.apply)

    print(f"\n== {args.role} network bootstrap {'applied' if args.apply else 'plan printed'} ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
