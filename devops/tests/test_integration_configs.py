from __future__ import annotations

import json
import re
from pathlib import Path

from conftest import ROOT, run_py


REQUIRED_ROBOT_SERVICES = {
    "core",
    "navigation",
    "ai",
    "perception",
    "speech",
    "tts",
    "safety",
    "dashboard-api",
    "monitoring",
}


def test_all_environment_configs_validate_with_required_host_overrides():
    overrides = {"BONBON_ROBOT_HOST": "robot.local", "BONBON_ROBOT_USER": "bonbon"}
    for environment in ["local_dev", "simulation", "lab_robot", "staging_robot", "production_robot"]:
        result = run_py("devops/scripts/validate_config.py", "--env", environment, env=overrides)
        assert result.returncode == 0, f"{environment}: {result.stderr}"


def test_robot_compose_contains_all_required_services(root: Path):
    text = (root / "deployment" / "compose" / "docker-compose.robot.yml").read_text(encoding="utf-8")
    for service in REQUIRED_ROBOT_SERVICES:
        assert re.search(rf"^  {re.escape(service)}:", text, re.MULTILINE), service


def test_systemd_units_map_to_robot_compose_services(root: Path):
    expected = {
        "bonbon-core.service": "core",
        "bonbon-navigation.service": "navigation",
        "bonbon-perception.service": "perception",
        "bonbon-speech.service": "speech",
        "bonbon-tts.service": "tts",
        "bonbon-safety.service": "safety",
        "bonbon-dashboard.service": "dashboard-api",
        "bonbon-monitoring.service": "monitoring",
    }
    for unit_name, compose_service in expected.items():
        unit = (root / "deployment" / "systemd" / unit_name).read_text(encoding="utf-8")
        assert f"up -d {compose_service}" in unit
        assert f"stop {compose_service}" in unit
        assert "EnvironmentFile=/etc/bonbon/bonbon.env" in unit


def test_safety_related_units_order_after_safety(root: Path):
    navigation = (root / "deployment" / "systemd" / "bonbon-navigation.service").read_text(encoding="utf-8")
    tts = (root / "deployment" / "systemd" / "bonbon-tts.service").read_text(encoding="utf-8")
    assert "Requires=bonbon-safety.service" in navigation
    assert "After=bonbon-core.service bonbon-safety.service" in tts


def test_robot_compose_uses_read_only_sensitive_mounts(root: Path):
    compose = (root / "deployment" / "compose" / "docker-compose.robot.yml").read_text(encoding="utf-8")
    for mount in ["/etc/bonbon:/config:ro", "/opt/bonbon/maps:/maps:ro", "/opt/bonbon/models:/models:ro"]:
        assert mount in compose
    assert "no-new-privileges:true" in compose


def test_dockerfiles_run_as_non_root_after_build(root: Path):
    for dockerfile in (root / "deployment" / "docker").glob("Dockerfile.*"):
        text = dockerfile.read_text(encoding="utf-8")
        assert "USER bonbon" in text, dockerfile


def test_dashboard_dockerfile_has_healthcheck(root: Path):
    text = (root / "deployment" / "docker" / "Dockerfile.dashboard").read_text(encoding="utf-8")
    assert "HEALTHCHECK" in text
    assert "/health" in text


def test_ci_workflow_contains_required_pipeline_stages(root: Path):
    ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for stage in [
        "Checkout",
        "Dependency install",
        "Python lint with ruff",
        "Formatting check with black",
        "Type check with mypy",
        "ROS2 dependency check with rosdep",
        "ROS2 build with colcon",
        "Unit tests",
        "Integration tests",
        "Safety tests",
        "Simulation smoke test",
        "Security scan",
        "Documentation check",
        "Docker image build",
        "Artifact upload",
    ]:
        assert stage in ci


def test_release_workflow_signs_and_verifies_artifacts(root: Path):
    release = (root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "sha256sum bonbon-release.tar.gz" in release
    assert "verify_release.py" in release
    assert "cosign sign-blob" in release


def test_prometheus_scrapes_required_metric_domains(root: Path):
    prometheus = (root / "deployment" / "monitoring" / "prometheus" / "prometheus.yml").read_text(
        encoding="utf-8"
    )
    for job in ["bonbon-dashboard", "bonbon-ros2-health", "node-exporter", "bonbon-safety", "bonbon-ai"]:
        assert job in prometheus


def test_grafana_dashboards_cover_required_views(root: Path):
    titles = []
    for path in (root / "deployment" / "monitoring" / "grafana" / "dashboards").glob("*.json"):
        titles.append(json.loads(path.read_text(encoding="utf-8"))["title"])
    expected_fragments = ["Robot Health", "Safety Status", "Navigation Performance", "AI Inference", "Logs"]
    for fragment in expected_fragments:
        assert any(fragment in title for title in titles), fragment


def test_no_plaintext_secret_assignments_in_deployment_tree(root: Path):
    secret_pattern = re.compile(r"BONBON_(JWT_SECRET|ADMIN_PASSWORD)=\S+")
    for path in list((root / "deployment").rglob("*")) + list((root / "devops").rglob("*")):
        if path.is_file() and path.suffix not in {".pyc"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert not secret_pattern.search(text), path
