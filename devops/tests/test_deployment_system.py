from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable


def run_py(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run([PYTHON, *args], cwd=ROOT, text=True, capture_output=True, env=merged)


def test_docker_build_success_check_files_exist():
    for name in [
        "Dockerfile.ros2",
        "Dockerfile.ai",
        "Dockerfile.navigation",
        "Dockerfile.dashboard",
    ]:
        path = ROOT / "deployment" / "docker" / name
        assert path.exists()
        assert "FROM " in path.read_text(encoding="utf-8")


def test_ros2_colcon_build_script_exists():
    text = (ROOT / "devops" / "scripts" / "build_ros2.sh").read_text(encoding="utf-8")
    assert "colcon build" in text
    assert "rosdep install" in text


def test_python_lint_configured():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.ruff]" in text


def test_python_formatting_configured():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.black]" in text


def test_python_type_checking_configured():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.mypy]" in text


def test_unit_test_execution_script_mentions_pytest():
    text = (ROOT / "devops" / "scripts" / "run_tests.sh").read_text(encoding="utf-8")
    assert "pytest" in text
    assert "bonbon_operator_api" in text


def test_integration_test_execution_in_ci():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "Integration tests" in text


def test_simulation_smoke_test_script():
    text = (ROOT / "devops" / "scripts" / "run_simulation_smoke.sh").read_text(encoding="utf-8")
    assert "test_ci_headless_run" in text


def test_config_validation_success_local_dev():
    result = run_py("devops/scripts/validate_config.py", "--env", "local_dev")
    assert result.returncode == 0, result.stderr


def test_deployment_dry_run_has_safety_gates():
    text = (ROOT / "devops" / "scripts" / "deploy_to_robot.sh").read_text(encoding="utf-8")
    assert "--dry-run" in text
    assert "BONBON_OPERATOR_AUTH_CONFIRMED" in text
    assert "rollback_version" in text
    assert "pre_deploy_check.py" in text
    assert "verify_release.py" in text
    assert "post_deploy_check.py" in text
    assert "bonbon.env" in text
    assert "BONBON_JWT_SECRET" in text


def test_rollback_dry_run_supported():
    text = (ROOT / "devops" / "scripts" / "rollback_robot.sh").read_text(encoding="utf-8")
    assert "run_cmd ssh" in text
    assert "BONBON_DRY_RUN" in (ROOT / "devops" / "scripts" / "common.sh").read_text(
        encoding="utf-8"
    )


def test_service_health_check_lists_required_services():
    text = (ROOT / "devops" / "scripts" / "health_check.sh").read_text(encoding="utf-8")
    for service in ["bonbon-core", "bonbon-navigation", "bonbon-safety", "bonbon-dashboard"]:
        assert service in text


def test_pre_deployment_safety_check_dry_run():
    result = run_py("devops/scripts/pre_deploy_check.py", "--dry-run")
    assert result.returncode == 0, result.stderr


def test_post_deployment_safety_check_dry_run():
    result = run_py("devops/scripts/post_deploy_check.py", "--dry-run")
    assert result.returncode == 0, result.stderr


def test_missing_environment_variable_fails_for_lab_robot():
    result = run_py("devops/scripts/validate_config.py", "--env", "lab_robot")
    assert result.returncode != 0
    assert "BONBON_ROBOT_HOST" in result.stderr


def test_environment_values_override_empty_runtime_template():
    result = run_py(
        "devops/scripts/validate_config.py",
        "--env",
        "lab_robot",
        env={"BONBON_ROBOT_HOST": "robot.local", "BONBON_ROBOT_USER": "bonbon"},
    )
    assert result.returncode == 0, result.stderr


def test_missing_model_file_detection(tmp_path: Path):
    root = tmp_path / "repo"
    config_dir = root / "devops" / "config" / "local_dev"
    config_dir.mkdir(parents=True)
    (config_dir / "runtime.env").write_text("BONBON_ENV=local_dev\n", encoding="utf-8")
    (config_dir / "services.yaml").write_text("environment: local_dev\n", encoding="utf-8")
    (config_dir / "models.manifest").write_text("models/missing.bin\n", encoding="utf-8")
    result = run_py("devops/scripts/validate_config.py", "--env", "local_dev", "--root", str(root))
    assert result.returncode != 0
    assert "missing model file" in result.stderr


def test_missing_config_file_detection(tmp_path: Path):
    root = tmp_path / "repo"
    config_dir = root / "devops" / "config" / "local_dev"
    config_dir.mkdir(parents=True)
    (config_dir / "runtime.env").write_text("BONBON_ENV=local_dev\n", encoding="utf-8")
    result = run_py("devops/scripts/validate_config.py", "--env", "local_dev", "--root", str(root))
    assert result.returncode != 0
    assert "missing config file" in result.stderr


def test_failed_service_startup_guarded_by_systemd_units():
    unit = (ROOT / "deployment" / "systemd" / "bonbon-core.service").read_text(encoding="utf-8")
    assert "TimeoutStartSec" in unit
    assert "ExecStop" in unit


def test_failed_deployment_rollback_documented():
    text = (ROOT / "deployment" / "docs" / "rollback_process.md").read_text(encoding="utf-8")
    assert "Rollback must be available before deployment starts" in text


def test_monitoring_stack_startup_configured():
    compose = (ROOT / "deployment" / "compose" / "docker-compose.simulation.yml").read_text(
        encoding="utf-8"
    )
    prometheus = (ROOT / "deployment" / "monitoring" / "prometheus" / "prometheus.yml").read_text(
        encoding="utf-8"
    )
    assert "prometheus" in compose
    assert "bonbon-safety" in prometheus


def test_log_collection_script():
    text = (ROOT / "devops" / "scripts" / "collect_logs.sh").read_text(encoding="utf-8")
    assert "journalctl" in text
    assert "/var/log/bonbon" in text


def test_version_generation(tmp_path: Path):
    output = tmp_path / "release.env"
    result = run_py(
        "devops/scripts/release_version.py", "--channel", "test", "--output", str(output)
    )
    assert result.returncode == 0, result.stderr
    text = output.read_text(encoding="utf-8")
    assert "BONBON_VERSION=test-" in text


def test_release_checksum_verification(tmp_path: Path):
    artifact = tmp_path / "artifact.txt"
    checksum = tmp_path / "artifact.txt.sha256"
    artifact.write_text("bonbon-release", encoding="utf-8")
    import hashlib

    checksum.write_text(
        f"{hashlib.sha256(b'bonbon-release').hexdigest()}  artifact.txt\n", encoding="utf-8"
    )
    result = run_py(
        "devops/scripts/verify_release.py",
        "--artifact",
        str(artifact),
        "--sha256",
        str(checksum),
    )
    assert result.returncode == 0, result.stderr


def test_rosdep_failures_are_not_masked():
    dockerfile = (ROOT / "deployment" / "docker" / "Dockerfile.ros2").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert (
        "rosdep install --from-paths ros2_ws/src --ignore-src -r -y --rosdistro humble &&"
        in dockerfile
    )
    assert (
        "rosdep install --from-paths ros2_ws/src --ignore-src -r -y --rosdistro humble || true"
        not in ci
    )


def test_deployment_audit_logging_present():
    common = (ROOT / "devops" / "scripts" / "common.sh").read_text(encoding="utf-8")
    deploy = (ROOT / "devops" / "scripts" / "deploy_to_robot.sh").read_text(encoding="utf-8")
    rollback = (ROOT / "devops" / "scripts" / "rollback_robot.sh").read_text(encoding="utf-8")
    assert "deployment_audit.log" in common
    assert "deploy_start" in deploy and "deploy_complete" in deploy
    assert "rollback_start" in rollback and "rollback_complete" in rollback


def test_grafana_dashboards_are_valid_json():
    for path in (ROOT / "deployment" / "monitoring" / "grafana" / "dashboards").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["title"].startswith("BonBon")
