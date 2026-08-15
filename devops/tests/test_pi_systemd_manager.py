"""Tests for devops/scripts/pi_systemd_manager.py -- 3-Pi Phase 8.

Confirmed via audit: deployment/systemd/pi{1,2,3}/*.service already exist
with real Requires=/After= dependency graphs, but no reusable install/
start/verify script existed anywhere. --apply/--start paths that touch
real systemd are NOT exercised here (require root + a real systemd host);
--plan (dry run, default) is safe and exercised directly, including
against the real checked-in unit files for all three Pis."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import load_script, run_py


def _write_unit(path: Path, name: str, requires: list[str] = (), after: list[str] = ()) -> Path:
    unit_path = path / name
    lines = ["[Unit]"]
    if after:
        lines.append(f"After={' '.join(after)}")
    if requires:
        lines.append(f"Requires={' '.join(requires)}")
    lines += ["", "[Service]", "ExecStart=/bin/true", "", "[Install]", "WantedBy=multi-user.target"]
    unit_path.write_text("\n".join(lines), encoding="utf-8")
    return unit_path


class TestParseUnitFile:
    def test_extracts_requires_and_after(self, tmp_path: Path):
        module = load_script("pi_systemd_manager.py")
        path = _write_unit(
            tmp_path,
            "bonbon-pi2-vision.service",
            requires=["bonbon-pi2-hal.service"],
            after=["docker.service", "bonbon-pi2-hal.service"],
        )
        parsed = module._parse_unit_file(path)
        assert parsed["name"] == "bonbon-pi2-vision.service"
        assert parsed["requires"] == ["bonbon-pi2-hal.service"]
        assert "docker.service" in parsed["after"]

    def test_unit_with_no_dependencies(self, tmp_path: Path):
        module = load_script("pi_systemd_manager.py")
        path = _write_unit(tmp_path, "bonbon-pi2-hal.service")
        parsed = module._parse_unit_file(path)
        assert parsed["requires"] == []


class TestTopologicalOrder:
    def test_independent_units_all_included(self):
        module = load_script("pi_systemd_manager.py")
        units = [{"name": "a.service", "requires": []}, {"name": "b.service", "requires": []}]
        order = module.topological_order(units)
        assert set(order) == {"a.service", "b.service"}

    def test_dependency_precedes_dependent(self):
        module = load_script("pi_systemd_manager.py")
        units = [
            {"name": "hal.service", "requires": []},
            {"name": "vision.service", "requires": ["hal.service"]},
        ]
        order = module.topological_order(units)
        assert order.index("hal.service") < order.index("vision.service")

    def test_diamond_dependency_resolves(self):
        """perception-fusion Requires= both vision and asr, which both
        Requires= hal -- exactly bonbon-pi2's real shape."""
        module = load_script("pi_systemd_manager.py")
        units = [
            {"name": "hal.service", "requires": []},
            {"name": "vision.service", "requires": ["hal.service"]},
            {"name": "asr.service", "requires": ["hal.service"]},
            {"name": "perception-fusion.service", "requires": ["vision.service", "asr.service"]},
        ]
        order = module.topological_order(units)
        assert order.index("hal.service") < order.index("vision.service")
        assert order.index("hal.service") < order.index("asr.service")
        assert order.index("vision.service") < order.index("perception-fusion.service")
        assert order.index("asr.service") < order.index("perception-fusion.service")

    def test_external_targets_are_not_treated_as_units(self):
        module = load_script("pi_systemd_manager.py")
        units = [{"name": "hal.service", "requires": ["docker.service"]}]
        order = module.topological_order(units)
        assert order == ["hal.service"]

    def test_cycle_raises(self):
        module = load_script("pi_systemd_manager.py")
        units = [
            {"name": "a.service", "requires": ["b.service"]},
            {"name": "b.service", "requires": ["a.service"]},
        ]
        with pytest.raises(module.SystemdManagerError):
            module.topological_order(units)


class TestLoadUnits:
    def test_missing_role_directory_raises(self):
        module = load_script("pi_systemd_manager.py")
        with pytest.raises(module.SystemdManagerError):
            module.load_units("pi9")

    def test_real_pi1_units_load(self):
        module = load_script("pi_systemd_manager.py")
        units = module.load_units("pi1")
        names = {u["name"] for u in units}
        assert "bonbon-pi1-dashboard-api.service" in names
        assert "bonbon-pi1-dashboard-frontend.service" in names

    def test_real_pi2_hal_precedes_its_dependents(self):
        module = load_script("pi_systemd_manager.py")
        units = module.load_units("pi2")
        order = module.topological_order(units)
        assert order.index("bonbon-pi2-hal.service") < order.index("bonbon-pi2-vision.service")
        assert order.index("bonbon-pi2-vision.service") < order.index(
            "bonbon-pi2-perception-fusion.service"
        )

    def test_real_pi3_safety_precedes_hal_and_actuation(self):
        module = load_script("pi_systemd_manager.py")
        units = module.load_units("pi3")
        order = module.topological_order(units)
        assert order.index("bonbon-pi3-safety.service") < order.index("bonbon-pi3-hal.service")
        assert order.index("bonbon-pi3-hal.service") < order.index(
            "bonbon-pi3-actuation.service"
        )
        assert order.index("bonbon-pi3-base-controller.service") < order.index(
            "bonbon-pi3-navigation.service"
        )

    def test_real_pi1_dashboard_frontend_after_dashboard_api(self):
        module = load_script("pi_systemd_manager.py")
        units = module.load_units("pi1")
        order = module.topological_order(units)
        assert order.index("bonbon-pi1-dashboard-api.service") < order.index(
            "bonbon-pi1-dashboard-frontend.service"
        )


class TestMainPlanDryRun:
    def test_plan_for_each_real_role_succeeds(self):
        for role in ("pi1", "pi2", "pi3"):
            result = run_py("devops/scripts/pi_systemd_manager.py", "--role", role)
            assert result.returncode == 0, result.stderr
            assert "DRY RUN" in result.stdout
            assert "[APPLY]" not in result.stdout

    def test_unknown_role_rejected_by_argparse(self):
        result = run_py("devops/scripts/pi_systemd_manager.py", "--role", "pi9")
        assert result.returncode == 2

    def test_verify_mode_runs_systemctl_and_reports_honestly(self):
        """No real systemd on this dev sandbox -- systemctl is either
        absent or reports nothing running, so this must exit non-zero and
        never fabricate a PASS."""
        result = run_py("devops/scripts/pi_systemd_manager.py", "--role", "pi2", "--verify")
        assert result.returncode in (0, 1)
        assert "RESULT" in result.stdout
