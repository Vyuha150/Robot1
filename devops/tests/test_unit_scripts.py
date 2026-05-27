from __future__ import annotations

import hashlib
import os
from pathlib import Path

from conftest import load_script, run_py


def test_validate_config_load_env_file_strips_quotes_and_ignores_comments(tmp_path: Path):
    module = load_script("validate_config.py")
    env_file = tmp_path / "runtime.env"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                "BONBON_ENV='lab_robot'",
                'BONBON_ROBOT_HOST="robot.local"',
                "EMPTY_VALUE=",
                "MALFORMED",
            ]
        ),
        encoding="utf-8",
    )
    values = module._load_env_file(env_file)
    assert values["BONBON_ENV"] == "lab_robot"
    assert values["BONBON_ROBOT_HOST"] == "robot.local"
    assert values["EMPTY_VALUE"] == ""
    assert "MALFORMED" not in values


def test_validate_config_rejects_runtime_secret_requirement_without_secrets(root: Path):
    result = run_py("devops/scripts/validate_config.py", "--env", "local_dev", "--require-runtime-secrets")
    assert result.returncode != 0
    assert "BONBON_JWT_SECRET" in result.stderr
    assert "BONBON_ADMIN_PASSWORD" in result.stderr


def test_validate_config_accepts_runtime_secret_requirement_from_environment(root: Path):
    result = run_py(
        "devops/scripts/validate_config.py",
        "--env",
        "local_dev",
        "--require-runtime-secrets",
        env={"BONBON_JWT_SECRET": "test-only", "BONBON_ADMIN_PASSWORD": "test-only"},
    )
    assert result.returncode == 0, result.stderr


def test_verify_release_sha256_matches_hashlib(tmp_path: Path):
    module = load_script("verify_release.py")
    artifact = tmp_path / "artifact.bin"
    payload = b"bonbon" * 128
    artifact.write_bytes(payload)
    assert module._sha256(artifact) == hashlib.sha256(payload).hexdigest()


def test_verify_release_rejects_bad_checksum(tmp_path: Path):
    artifact = tmp_path / "artifact.bin"
    checksum = tmp_path / "artifact.bin.sha256"
    artifact.write_text("payload", encoding="utf-8")
    checksum.write_text("0" * 64 + " artifact.bin\n", encoding="utf-8")
    result = run_py("devops/scripts/verify_release.py", "--artifact", str(artifact), "--sha256", str(checksum))
    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr


def test_verify_release_rejects_missing_checksum(tmp_path: Path):
    artifact = tmp_path / "artifact.bin"
    artifact.write_text("payload", encoding="utf-8")
    result = run_py(
        "devops/scripts/verify_release.py",
        "--artifact",
        str(artifact),
        "--sha256",
        str(tmp_path / "missing.sha256"),
    )
    assert result.returncode != 0
    assert "checksum file missing" in result.stderr


def test_release_version_writes_artifact_checksum(tmp_path: Path):
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("release-payload", encoding="utf-8")
    output = tmp_path / "release.env"
    result = run_py(
        "devops/scripts/release_version.py",
        "--channel",
        "lab",
        "--output",
        str(output),
        "--artifact",
        str(artifact),
    )
    assert result.returncode == 0, result.stderr
    text = output.read_text(encoding="utf-8")
    assert "BONBON_VERSION=lab-" in text
    assert "SHA256_ARTIFACT_TXT=" in text


def test_pre_deploy_non_dry_run_fails_closed_without_safety_env():
    env = {key: "" for key in os.environ if key.startswith("BONBON_")}
    result = run_py("devops/scripts/pre_deploy_check.py", env=env)
    assert result.returncode != 0
    assert "battery above threshold" in result.stderr
    assert "emergency stop available" in result.stderr


def test_pre_deploy_non_dry_run_accepts_required_safety_env():
    result = run_py(
        "devops/scripts/pre_deploy_check.py",
        env={
            "BONBON_MIN_BATTERY_PCT": "40",
            "BONBON_CURRENT_BATTERY_PCT": "85",
            "BONBON_ESTOP_AVAILABLE": "1",
            "BONBON_SAFETY_SUPERVISOR_RUNNING": "1",
            "BONBON_ROBOT_TASK_PAUSED": "1",
            "BONBON_NO_ACTIVE_NAVIGATION": "1",
            "BONBON_ROLLBACK_VERSION": "previous",
            "BONBON_SERVICE_HEALTH_OK": "1",
            "BONBON_OPERATOR_AUTH_CONFIRMED": "1",
            "BONBON_MIN_DISK_FREE_FRACTION": "0.0",
        },
    )
    assert result.returncode == 0, result.stderr


def test_post_deploy_non_dry_run_fails_closed_on_missing_runtime():
    result = run_py("devops/scripts/post_deploy_check.py", env={})
    assert result.returncode != 0
    assert "Post-deployment checks failed" in result.stderr


def test_pre_and_post_deploy_truthy_parser_accepts_expected_values():
    pre = load_script("pre_deploy_check.py")
    post = load_script("post_deploy_check.py")
    for value in ["1", "true", "yes", "ok"]:
        os.environ["BONBON_TEST_TRUTHY"] = value
        assert pre._truthy("BONBON_TEST_TRUTHY", dry_run=False)
        assert post._truthy("BONBON_TEST_TRUTHY", dry_run=False)
