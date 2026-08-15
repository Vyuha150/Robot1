"""Tests for devops/scripts/bootstrap_pi_network.py and
devops/scripts/check_inter_pi_communication.py -- 3-Pi Phase 7 remainder.
Confirmed via audit: these two scripts existed with zero test coverage
anywhere in the repo.

bootstrap_pi_network.py defaults to dry-run (never touches the real
system without --apply) so its main() is safe to exercise directly here.
--apply itself is NOT tested -- it requires root and calls nmcli/chrony/
hostnamectl, none of which belong in a unit test, and os.geteuid() is
POSIX-only (this script is Pi/Linux-only tooling by design).

check_inter_pi_communication.py is read-only (ping + `ros2 topic list` +
bounded `ros2 topic echo`) -- safe to run for real. On this dev sandbox
the configured peer IPs are unreachable and `ros2` is not on PATH, so it
deterministically reports FAIL/exit 1 -- that is itself the behavior under
test (it must fail loudly, not silently report success)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from conftest import load_script, run_py


# ── bootstrap_pi_network.py ────────────────────────────────────────────────


def _valid_network_config(tmp_path: Path) -> Path:
    cfg = {
        "pis": {
            "pi1": {"role": "ui_api", "hostname": "test-pi1", "static_ip": "192.168.10.11"},
            "pi2": {"role": "human_ai", "hostname": "test-pi2", "static_ip": "192.168.10.12"},
            "pi3": {
                "role": "navigation_safety",
                "hostname": "test-pi3",
                "static_ip": "192.168.10.13",
            },
        },
        "ros2": {
            "ros_domain_id": 42,
            "rmw_implementation": "rmw_cyclonedds_cpp",
            "dds_profile_file": "config/distributed/cyclonedds_ethernet_profile.xml",
        },
        "time_sync": {"server": "pi3"},
    }
    path = tmp_path / "robot_network.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


class TestLoadNetworkConfig:
    def test_missing_file_raises(self):
        module = load_script("bootstrap_pi_network.py")
        with pytest.raises(module.BootstrapError):
            module._load_network_config(Path("/nonexistent/robot_network.yaml"))

    def test_missing_required_section_raises(self, tmp_path: Path):
        module = load_script("bootstrap_pi_network.py")
        path = tmp_path / "robot_network.yaml"
        path.write_text(yaml.safe_dump({"pis": {}}), encoding="utf-8")
        with pytest.raises(module.BootstrapError, match="ros2"):
            module._load_network_config(path)

    def test_valid_file_loads(self, tmp_path: Path):
        module = load_script("bootstrap_pi_network.py")
        cfg = module._load_network_config(_valid_network_config(tmp_path))
        assert cfg["pis"]["pi2"]["static_ip"] == "192.168.10.12"


class TestUpsertEnvFile:
    def test_creates_new_file_with_all_keys(self, tmp_path: Path):
        module = load_script("bootstrap_pi_network.py")
        path = tmp_path / "bonbon.env"
        module._upsert_env_file(path, {"ROS_DOMAIN_ID": "42", "RMW_IMPLEMENTATION": "x"}, apply=True)
        content = path.read_text(encoding="utf-8")
        assert "ROS_DOMAIN_ID=42" in content
        assert "RMW_IMPLEMENTATION=x" in content

    def test_preserves_unrelated_existing_keys(self, tmp_path: Path):
        module = load_script("bootstrap_pi_network.py")
        path = tmp_path / "bonbon.env"
        path.write_text("BONBON_EXISTING_KEEPME=keepme\n", encoding="utf-8")
        module._upsert_env_file(path, {"ROS_DOMAIN_ID": "42"}, apply=True)
        content = path.read_text(encoding="utf-8")
        assert "BONBON_EXISTING_KEEPME=keepme" in content
        assert "ROS_DOMAIN_ID=42" in content

    def test_overwrites_matching_key(self, tmp_path: Path):
        module = load_script("bootstrap_pi_network.py")
        path = tmp_path / "bonbon.env"
        path.write_text("ROS_DOMAIN_ID=0\n", encoding="utf-8")
        module._upsert_env_file(path, {"ROS_DOMAIN_ID": "42"}, apply=True)
        content = path.read_text(encoding="utf-8")
        assert "ROS_DOMAIN_ID=42" in content
        assert "ROS_DOMAIN_ID=0" not in content

    def test_dry_run_does_not_write(self, tmp_path: Path):
        module = load_script("bootstrap_pi_network.py")
        path = tmp_path / "bonbon.env"
        module._upsert_env_file(path, {"ROS_DOMAIN_ID": "42"}, apply=False)
        assert not path.exists()


class TestBootstrapMainDryRun:
    def test_dry_run_succeeds_and_never_applies(self, tmp_path: Path, root: Path):
        network_config = _valid_network_config(tmp_path)
        result = run_py(
            "devops/scripts/bootstrap_pi_network.py",
            "--role",
            "pi2",
            "--network-config",
            str(network_config),
        )
        assert result.returncode == 0
        assert "DRY RUN" in result.stdout
        assert "[APPLY]" not in result.stdout

    def test_unknown_role_rejected_by_argparse(self, tmp_path: Path):
        network_config = _valid_network_config(tmp_path)
        result = run_py(
            "devops/scripts/bootstrap_pi_network.py",
            "--role",
            "pi9",
            "--network-config",
            str(network_config),
        )
        assert result.returncode == 2

    def test_role_not_in_config_fails_with_exit_1(self, tmp_path: Path):
        module = load_script("bootstrap_pi_network.py")
        cfg = {
            "pis": {"pi1": {"role": "ui_api", "hostname": "h", "static_ip": "192.168.10.11"}},
            "ros2": {"ros_domain_id": 42, "rmw_implementation": "x", "dds_profile_file": "x"},
            "time_sync": {"server": "pi1"},
        }
        path = tmp_path / "robot_network.yaml"
        path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        rc = module.main(["--role", "pi2", "--network-config", str(path)])
        assert rc == 1


# ── check_inter_pi_communication.py ────────────────────────────────────────


class TestCheckDomainId:
    def test_matching_domain_id_passes(self, monkeypatch: pytest.MonkeyPatch):
        module = load_script("check_inter_pi_communication.py")
        monkeypatch.setenv("ROS_DOMAIN_ID", "42")
        ok, msg = module._check_domain_id(42)
        assert ok is True
        assert "matches" in msg

    def test_missing_domain_id_fails(self, monkeypatch: pytest.MonkeyPatch):
        module = load_script("check_inter_pi_communication.py")
        monkeypatch.delenv("ROS_DOMAIN_ID", raising=False)
        ok, msg = module._check_domain_id(42)
        assert ok is False
        assert "not set" in msg

    def test_mismatched_domain_id_fails(self, monkeypatch: pytest.MonkeyPatch):
        module = load_script("check_inter_pi_communication.py")
        monkeypatch.setenv("ROS_DOMAIN_ID", "7")
        ok, msg = module._check_domain_id(42)
        assert ok is False
        assert "expected 42" in msg


class TestCheckTopicAdvertised:
    def test_topic_present_passes(self):
        module = load_script("check_inter_pi_communication.py")
        ok, msg = module._check_topic_advertised("/bonbon/pi2/heartbeat", ["/bonbon/pi2/heartbeat"])
        assert ok is True

    def test_topic_absent_fails(self):
        module = load_script("check_inter_pi_communication.py")
        ok, msg = module._check_topic_advertised("/bonbon/pi2/heartbeat", ["/other/topic"])
        assert ok is False

    def test_none_topic_list_fails_honestly(self):
        """ros2 not on PATH -- must report failure, not silently pass."""
        module = load_script("check_inter_pi_communication.py")
        ok, msg = module._check_topic_advertised("/bonbon/pi2/heartbeat", None)
        assert ok is False
        assert "ros2 not on PATH" in msg


class TestCheckMainAgainstCheckedInConfig:
    def test_reports_failure_when_peers_unreachable(self, root: Path):
        """This dev sandbox has no route to the real Pi static IPs and no
        `ros2` on PATH -- the script must exit non-zero and print FAIL
        lines, never a fabricated PASS."""
        result = run_py(
            "devops/scripts/check_inter_pi_communication.py",
            "--role",
            "pi1",
            "--skip-live-data",
            timeout=20,
        )
        assert result.returncode == 1
        assert "FAIL" in result.stdout
        assert "INTER-PI COMMUNICATION PROBLEM DETECTED" in result.stdout
