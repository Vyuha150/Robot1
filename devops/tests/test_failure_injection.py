from __future__ import annotations

from pathlib import Path

from conftest import run_py


def test_config_validation_fails_on_unknown_environment():
    result = run_py("devops/scripts/validate_config.py", "--env", "unknown")
    assert result.returncode != 0
    assert "invalid choice" in result.stderr


def test_config_validation_fails_when_config_directory_missing(tmp_path: Path):
    root = tmp_path / "empty_repo"
    root.mkdir()
    result = run_py("devops/scripts/validate_config.py", "--env", "local_dev", "--root", str(root))
    assert result.returncode != 0
    assert "missing config directory" in result.stderr


def test_pre_deploy_rejects_low_battery_even_when_other_checks_pass():
    result = run_py(
        "devops/scripts/pre_deploy_check.py",
        env={
            "BONBON_MIN_BATTERY_PCT": "80",
            "BONBON_CURRENT_BATTERY_PCT": "20",
            "BONBON_ESTOP_AVAILABLE": "1",
            "BONBON_SAFETY_SUPERVISOR_RUNNING": "1",
            "BONBON_ROBOT_TASK_PAUSED": "1",
            "BONBON_NO_ACTIVE_NAVIGATION": "1",
            "BONBON_ROLLBACK_VERSION": "previous",
            "BONBON_SERVICE_HEALTH_OK": "1",
            "BONBON_OPERATOR_AUTH_CONFIRMED": "1",
        },
    )
    assert result.returncode != 0
    assert "battery above threshold" in result.stderr


def test_pre_deploy_rejects_active_navigation():
    result = run_py(
        "devops/scripts/pre_deploy_check.py",
        env={
            "BONBON_MIN_BATTERY_PCT": "40",
            "BONBON_CURRENT_BATTERY_PCT": "90",
            "BONBON_ESTOP_AVAILABLE": "1",
            "BONBON_SAFETY_SUPERVISOR_RUNNING": "1",
            "BONBON_ROBOT_TASK_PAUSED": "1",
            "BONBON_NO_ACTIVE_NAVIGATION": "0",
            "BONBON_ROLLBACK_VERSION": "previous",
            "BONBON_SERVICE_HEALTH_OK": "1",
            "BONBON_OPERATOR_AUTH_CONFIRMED": "1",
        },
    )
    assert result.returncode != 0
    assert "no active navigation" in result.stderr


def test_verify_release_rejects_missing_artifact(tmp_path: Path):
    checksum = tmp_path / "missing.sha256"
    checksum.write_text("0" * 64 + " missing.bin\n", encoding="utf-8")
    result = run_py(
        "devops/scripts/verify_release.py",
        "--artifact",
        str(tmp_path / "missing.bin"),
        "--sha256",
        str(checksum),
    )
    assert result.returncode != 0
    assert "release artifact missing" in result.stderr


def test_post_deploy_dry_run_masks_external_dependency_absence():
    result = run_py("devops/scripts/post_deploy_check.py", "--dry-run")
    assert result.returncode == 0, result.stderr
