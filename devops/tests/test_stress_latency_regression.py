from __future__ import annotations

import hashlib
import time
from pathlib import Path

from conftest import ROOT, run_py


def test_stress_validate_all_configs_repeatedly():
    start = time.perf_counter()
    overrides = {"BONBON_ROBOT_HOST": "robot.local", "BONBON_ROBOT_USER": "bonbon"}
    environments = ["local_dev", "simulation", "lab_robot", "staging_robot", "production_robot"]
    for _ in range(10):
        for environment in environments:
            result = run_py(
                "devops/scripts/validate_config.py", "--env", environment, env=overrides
            )
            assert result.returncode == 0, result.stderr
    elapsed = time.perf_counter() - start
    assert elapsed < 35.0


def test_latency_pre_deploy_dry_run_is_fast():
    start = time.perf_counter()
    for _ in range(25):
        result = run_py("devops/scripts/pre_deploy_check.py", "--dry-run")
        assert result.returncode == 0, result.stderr
    elapsed = time.perf_counter() - start
    assert elapsed < 10.0


def test_latency_checksum_verification_large_artifact(tmp_path: Path):
    artifact = tmp_path / "large-artifact.bin"
    payload = b"0123456789abcdef" * 128 * 1024
    artifact.write_bytes(payload)
    checksum = tmp_path / "large-artifact.bin.sha256"
    checksum.write_text(
        f"{hashlib.sha256(payload).hexdigest()}  large-artifact.bin\n", encoding="utf-8"
    )
    start = time.perf_counter()
    result = run_py(
        "devops/scripts/verify_release.py",
        "--artifact",
        str(artifact),
        "--sha256",
        str(checksum),
    )
    elapsed = time.perf_counter() - start
    assert result.returncode == 0, result.stderr
    assert elapsed < 5.0


def test_regression_no_deployment_script_hardcodes_robot_ip():
    for script in (ROOT / "devops" / "scripts").glob("*.sh"):
        text = script.read_text(encoding="utf-8")
        assert "192.168." not in text
        assert "10.0." not in text
        assert "robot.local" not in text


def test_regression_deployment_preserves_existing_runtime_secrets():
    deploy = (ROOT / "devops" / "scripts" / "deploy_to_robot.sh").read_text(encoding="utf-8")
    assert "BONBON_JWT_SECRET|BONBON_ADMIN_PASSWORD" in deploy
    assert "install -m 0640" in deploy


def test_regression_release_metadata_is_ignored_by_gitignore():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "deployment/ota/release_metadata.env" in gitignore
    assert "deployment/logs/" in gitignore


def test_simulation_smoke_executes_headless_scenario_runner():
    scenario = (
        ROOT
        / "ros2_ws"
        / "src"
        / "bonbon_simulation"
        / "scenarios"
        / "hospital_corridor_navigation.yaml"
    )
    config = ROOT / "ros2_ws" / "src" / "bonbon_simulation" / "config" / "simulation_params.yaml"
    env = {
        "PYTHONPATH": str(ROOT / "ros2_ws" / "src" / "bonbon_simulation"),
    }
    result = run_py(
        "-m",
        "bonbon_simulation.core.runner",
        str(scenario),
        "--config",
        str(config),
        "--no-report",
        env=env,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_stress_release_version_generation_repeatedly(tmp_path: Path):
    for index in range(10):
        output = tmp_path / f"release_{index}.env"
        result = run_py(
            "devops/scripts/release_version.py", "--channel", "stress", "--output", str(output)
        )
        assert result.returncode == 0, result.stderr
        assert output.exists()
